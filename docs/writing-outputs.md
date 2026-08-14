[← Back to README](../README.md) · [Tutorial](tutorial.md) · [How-to guides](how-to-guides.md) · [Reference](reference.md) · [Explanation](explanation.md)

# Writing outputs.tf for a good garnish page

This page is for whoever (or whatever) is authoring `outputs.tf`, not for
consuming the action. Point an AI coding agent at it (link it from your
repo's `AGENTS.md`/`CLAUDE.md`) when you want generated Tofu to render well
on a tofu-garnish page instead of just being valid HCL.

## Name outputs so alphabetical order reads well

tofu-garnish has no grouping concept: outputs are rendered in a single list,
sorted by name (`Output.name.lower()`). That sort order is the only
structure the page has, so it doubles as the page's information
architecture. Prefix related outputs consistently:

```hcl
output "vpc_id" { ... }
output "vpc_cidr" { ... }
output "vpc_subnet_ids" { ... }
```

not

```hcl
output "id" { ... }          # which resource?
output "subnets" { ... }
output "cidr_block" { ... }  # sorts nowhere near the other two
```

## Always set description

`description` is the only prose that reaches the page (OpenTofu only, via
`tofu show -json -module`; see [Explanation](explanation.md#why-opentofu-only-for-descriptions)
for why Terraform can't provide it). An output with no `description` renders
with just its name and value, no context for the person reading it:

```hcl
output "vpc_id" {
  value       = aws_vpc.main.id
  description = "VPC ID for the shared network stack."
}
```

## Keep sibling objects shape-uniform

A list of dicts always becomes a columnar table: one row per item, one
column per key seen across the whole list. Uniform shapes give a clean
table; a list with inconsistent keys still renders as one, but with `—` in
every cell where an item is missing that column, so keep the keys
consistent:

```hcl
output "subnets" {
  value = [
    for s in aws_subnet.this : {
      id   = s.id
      cidr = s.cidr_block
      az   = s.availability_zone
    }
  ]
  description = "Subnets in the shared VPC."
}
```

A one-off nested structure is fine as a map (renders as a key/value table);
save list-of-objects for genuinely repeated shapes.

## Mark sensitive outputs sensitive

```hcl
output "db_password" {
  value       = random_password.db.result
  sensitive   = true
  description = "Superuser password for the RDS instance."
}
```

`sensitive = true` masks the value on the page and drops it from
`outputs.json` entirely (see [sensitive value handling](explanation.md#sensitive-values)).
Don't rely on a vague name or a missing description to hide something that
belongs in a secrets manager instead of an output.

## Flatten what should be copy-button-friendly

Every top-level row gets a single copy button: plain text for scalars,
pretty JSON for anything nested. If an output's whole purpose is "the thing
someone pastes into a CLI or console field", make it a scalar rather than a
field buried three levels into a map.
