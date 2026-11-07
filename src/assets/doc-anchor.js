document.addEventListener('click', function (e) {
  var a = e.target.closest('a.anchor');
  if (!a) { return; }
  var url = location.href.split('#')[0] + a.getAttribute('href');
  history.replaceState(null, '', a.getAttribute('href'));
  if (navigator.clipboard) { navigator.clipboard.writeText(url); }
  a.textContent = '\u2713';
  setTimeout(function () { a.textContent = '#'; }, 1200);
});
