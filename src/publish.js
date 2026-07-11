// Publish the generated tofu-garnish site to a Pages branch via the GitHub
// Git Data API. Called from actions/github-script, so no clone, no
// credential plumbing: the base_tree mechanism preserves every file already
// on the branch and only overwrites the ones this run generates.
//
// Expects in the environment: PAGES_BRANCH, GARNISH_ACTION_PATH, plus
// everything src/generate.sh needs (GARNISH_SCRIPT, GARNISH_TITLE and one of
// GARNISH_WORKSPACES / GARNISH_OUTPUTS_FILE / GARNISH_OUTPUTS).

const fs = require("fs");
const os = require("os");
const path = require("path");

function collectFiles(dir, prefix = "") {
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      files.push(...collectFiles(path.join(dir, entry.name), rel));
    } else {
      files.push({
        path: rel,
        content: fs.readFileSync(path.join(dir, entry.name), "utf8"),
      });
    }
  }
  return files;
}

module.exports = async ({ github, context, core, exec }) => {
  const branch = process.env.PAGES_BRANCH;
  const actionPath = process.env.GARNISH_ACTION_PATH;
  const { owner, repo } = context.repo;
  const mergeMode = Boolean(process.env.GARNISH_WORKSPACES);

  const getTip = async () => {
    try {
      const ref = await github.rest.git.getRef({ owner, repo, ref: `heads/${branch}` });
      return ref.data.object.sha;
    } catch (error) {
      if (error.status === 404) return null;
      throw error;
    }
  };

  const attempts = 3;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const tip = await getTip();
    const siteDir = fs.mkdtempSync(path.join(os.tmpdir(), "tofu-garnish-"));

    // Seed the existing manifest so garnish --merge preserves other workspaces.
    if (tip && mergeMode) {
      try {
        const res = await github.rest.repos.getContent({
          owner,
          repo,
          path: "manifest.json",
          ref: branch,
        });
        fs.writeFileSync(
          path.join(siteDir, "manifest.json"),
          Buffer.from(res.data.content, "base64"),
        );
      } catch (error) {
        if (error.status !== 404) throw error;
      }
    }

    await exec.exec("bash", [path.join(actionPath, "src", "generate.sh"), siteDir]);
    fs.writeFileSync(path.join(siteDir, ".nojekyll"), "");
    core.setOutput("site-dir", siteDir);

    try {
      const baseTree = tip
        ? (await github.rest.git.getCommit({ owner, repo, commit_sha: tip })).data.tree.sha
        : undefined;
      const tree = await github.rest.git.createTree({
        owner,
        repo,
        base_tree: baseTree,
        tree: collectFiles(siteDir).map((file) => ({
          path: file.path,
          mode: "100644",
          type: "blob",
          content: file.content,
        })),
      });
      const commit = await github.rest.git.createCommit({
        owner,
        repo,
        message: "tofu-garnish: update outputs site [skip ci]",
        tree: tree.data.sha,
        parents: tip ? [tip] : [],
      });
      if (tip) {
        await github.rest.git.updateRef({
          owner,
          repo,
          ref: `heads/${branch}`,
          sha: commit.data.sha,
        });
      } else {
        await github.rest.git.createRef({
          owner,
          repo,
          ref: `refs/heads/${branch}`,
          sha: commit.data.sha,
        });
      }
      core.info(`published ${commit.data.sha.slice(0, 7)} to '${branch}'`);
      break;
    } catch (error) {
      if (attempt === attempts) throw error;
      core.info(`push to '${branch}' conflicted (attempt ${attempt}), retrying: ${error.message}`);
      await new Promise((resolve) => setTimeout(resolve, attempt * 1000));
    }
  }

  try {
    const pages = await github.rest.repos.getPages({ owner, repo });
    core.setOutput("page-url", pages.data.html_url || "");
  } catch {
    core.setOutput("page-url", "");
  }
};
