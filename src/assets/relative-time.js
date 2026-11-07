document.querySelectorAll('time[datetime]').forEach(function (t) {
  var s = (Date.now() - Date.parse(t.getAttribute('datetime'))) / 1000;
  if (isNaN(s) || s < 0) { return; }
  var units = [[86400, 'day'], [3600, 'hour'], [60, 'minute']];
  for (var i = 0; i < units.length; i++) {
    var n = Math.floor(s / units[i][0]);
    if (n >= 1) {
      t.textContent = n + ' ' + units[i][1] + (n === 1 ? '' : 's') + ' ago';
      return;
    }
  }
  t.textContent = 'just now';
});
