var token, repos = [], pushUrl;

function bakeCookies() {
  var rv = {},
      cookies = document.cookie.split('; ');
  for (var i in cookies) {
    var kv = cookies[i].split('=');
    rv[kv[0]] = kv[1];
  }
  return rv;
}

function getUserData() {
  var promise = $.Deferred();
  if (localStorage.getItem('userData')) {
    promise.resolve(JSON.parse(localStorage.getItem('userData')));
    return promise;
  }

  var xhr = $.getJSON('https://api.github.com/user?access_token=' + token, function(d) {
    localStorage.setItem('userData', JSON.stringify(d));
  });
  return xhr;
}

function fetchRepos(userData) {
  var numRepos = userData.public_repos + (userData.owned_private_repos || 0),
      pages = Math.ceil(numRepos / 30),
      promises = [];


  for (var i = 0; i < pages; i++) {
    var base = 'https://api.github.com/user/repos',
        url = base + '?page=' + (i + 1) + '&access_token=' + token;
    promises.push($.getJSON(url, function(rs) { repos = repos.concat(rs); }));
  }

  return $.when.apply($, promises).done(function() {
    repos.sort(function(a, b) {
      var atime = new Date(a.pushed_at), btime = new Date(b.pushed_at);
      if (atime < btime)
        return 1;
      if (btime < atime)
        return -1;
      return 0;
    });
  });
}

function addHook(repo) {
  var data = {name: 'web',
              active: true,
              config: {url: document.location + 'hook'}};
  $.ajax({
    url: repo.url + '/hooks?access_token=' + token,
    type: 'POST',
    data: JSON.stringify(data),
    contentType: 'application/json',
  }).done(function(e) {
    // Store the hook id in localstorage.
  }, function() {
    $.post('/subscribe', {repo: repo.url, access_token: token});
  });
}

function main() {
  step1().pipe(step2).pipe(step3).pipe(step4);

  $('#repos').on('click', 'button.add', function() {
    var link = $(this).parent().find('a').attr('href'),
        repoHash = {};
    $.each(repos, function(i, el) { repoHash[el.html_url] = el; });

    addHook(repoHash[link]);
  });
}

function step1() {
  var promise = $.Deferred();
  $(document).trigger('step', [1]);

  function test() {
    var notification = navigator.mozNotification;
    return !!(notification && notification.requestRemotePermission);
  }

  if (test()) {
    promise.resolve();
  } else {
    var interval = setInterval(function() {
      if (test()) {
        clearInterval(interval);
        promise.resolve();
      }
    }, 1000);
  }
  return promise;
}

function step2() {
  $(document).trigger('step', [2]);
  var promise = $.Deferred();

  var notification = navigator.mozNotification,
      check = notification.checkRemotePermission();
  check.onsuccess = function() {
    if (check.result.url) {
      pushUrl = check.result.url;
      promise.resolve();
    } else {
      var request = notification.requestRemotePermission();
      request.onsuccess = function() {
        pushUrl = request.result.url;
        promise.resolve();
      };
      request.onerror = function() {
        alert('error requesting remote permission');
      };
    }
  };
  check.onerror = function() {
    alert('error checking remote permission');
  }
  return promise;
}


function step3() {
  $(document).trigger('step', [3]);
  var promise = $.Deferred(),
      cookies = bakeCookies();
  if (cookies.username && cookies.access_token) {
    token = cookies.access_token;
    $.post('/queue', {queue: pushUrl, access_token: token});
    promise.resolve();
  }
  return promise;
}


function step4() {
  $(document).trigger('step', [4]);
  var promise = getUserData();
  promise.pipe(fetchRepos).then(function() {
    $('#repos').html(Mustache.render($('#repos-template').text(), {repos: repos}));
  });
}


$(document).bind('step', function(e, step) {
  console.log('step', step);
  $('.showing').removeClass('showing');
  $('#step-' + step).addClass('showing');
});

$(document).ready(main);
