(function () {
  var live = document.createElement('p');
  live.className = 'sr-only';
  live.setAttribute('role', 'status');
  document.body.appendChild(live);
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('button.copy');
    if (!btn) { return; }
    var label = btn.innerHTML;
    var box = btn.getBoundingClientRect();
    navigator.clipboard.writeText(btn.dataset.raw).then(function () {
      btn.style.boxSizing = 'border-box';
      btn.style.width = box.width + 'px';
      btn.style.height = box.height + 'px';
      btn.style.flex = 'none';
      btn.style.overflow = 'hidden';
      btn.style.whiteSpace = 'nowrap';
      btn.textContent = btn.dataset.done || '\u2713';
      live.textContent = 'Copied';
      setTimeout(function () {
        btn.innerHTML = label;
        btn.removeAttribute('style');
        live.textContent = '';
      }, 1200);
    });
  });
})();
