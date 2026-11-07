(function () {
  var input = document.getElementById('filter');
  var announce = document.getElementById('filter-status');
  var sections = document.querySelectorAll('section.output, section.removed');
  input.addEventListener('input', function () {
    var q = this.value.trim().toLowerCase();
    var shown = 0;
    sections.forEach(function (s) {
      var show = !q || s.dataset.search.indexOf(q) !== -1;
      s.style.display = show ? '' : 'none';
      if (show) {
        shown += 1;
        s.querySelectorAll('details').forEach(function (d) {
          if (d.dataset.o === undefined) { d.dataset.o = d.open ? '1' : ''; }
          d.open = q ? true : d.dataset.o === '1';
        });
      }
    });
    document.getElementById('no-match').style.display = shown ? 'none' : 'block';
    if (announce) { announce.textContent = q ? shown + ' of ' + sections.length + ' shown' : ''; }
  });
})();
