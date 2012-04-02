var token, username, repos = [], orgRepos = [], repoMap = {}, pushUrl;

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

  return $.when.apply($, promises).done(function() { sortRepos(repos); });
}

function sortRepos(arr) {
  arr.sort(function(a, b) {
    var atime = new Date(a.pushed_at), btime = new Date(b.pushed_at);
    if (atime < btime)
      return 1;
    if (btime < atime)
      return -1;
    return 0;
  });

  $.each(arr, function(i, el) { repoMap[el.id] = el; });
}

function getOrgData() {
  return $.getJSON('https://api.github.com/user/orgs?access_token=' + token);
}

function getOrgRepos(orgs) {
  return $.when.apply($, orgs.map(function(org) {
    return $.getJSON(org.url + '/repos?type=member&access_token=' + token);
  }));
}

function addOrgRepos() {
  getOrgData().pipe(getOrgRepos).done(function() {
    var rs = [].map.call(arguments, function(e){ return e[0]; });
    orgRepos = [].concat.apply([], rs);
    sortRepos(orgRepos);
    render();
  });
}

function saveHook(repo, hook) {
  var hooks = getHooks();
  hooks[repo.id] = hook.url;
  localStorage.setItem('hooks', JSON.stringify(hooks));
}

function getHooks() {
  return JSON.parse(localStorage.getItem('hooks') || '{}');
}

function addHook(repo) {
  var url = repo.url + '/hooks?access_token=' + token,
      data = {name: 'web',
              active: true,
              config: {url: document.location + 'hook'}};

  var promise = $.Deferred().done(function(hook) {
    saveHook(repo, hook);
    render();
    $.post('/subscribe', {repo: repo.url});
  });

  $.getJSON(url, function(hooks) {
    var hookMap = {};
    $.each(hooks, function(i, h) { hookMap[h.config.url] = h; });

    if (data.config.url in hookMap) {
      promise.resolve(hookMap[data.config.url]);
    } else {
      $.ajax({
        url: url,
        type: 'POST',
        data: JSON.stringify(data),
        dataType: 'json',
        contentType: 'application/json',
      }).done(function(d){ promise.resolve(d); });
    }
  }).fail(function() {
    repoMap[repo.id].denied = true;
    render();
  });
}

function removeHook(repo) {
  var hooks = getHooks(),
      hook = hooks[repo.id];
  $.post('/unsubscribe', {repo: repo.url}, function(d) {
    delete hooks[repo.id];
    localStorage.setItem('hooks', JSON.stringify(hooks));
    if (d.count === 0) {
      $.ajax({url: hook + '?access_token=' + token, type: 'DELETE'});
    }
  });
  render();
}

function main() {
  if (localStorage.getItem('version') !== '2') {
    localStorage.removeItem('username');
    localStorage.removeItem('access_token');
    localStorage.setItem('version', '2');
  }

  step1().pipe(step2).pipe(step3).pipe(step4);

  var $repos = $('#repos');
  $repos.on('click', 'button.add', function() {
    var id = $(this).parent().attr('data-id');
    addHook(repoMap[id]);
  }).on('click', 'button.test', function() {
    var id = $(this).parent().attr('data-id');
    var hook = getHooks()[id];
    if (hook) {
      $.post(hook + '/test?access_token=' + token);
    }
  }).on('click', 'button.disconnect', function() {
    var id = $(this).parent().attr('data-id');
    removeHook(repoMap[id]);
  }).on('click', '.repo-type', function() {
    $repos.toggleClass('org');
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
  $('#step-2 li:first-child').addClass('selected');
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
  promise.done(function() {
   console.log('Your push URL:', pushUrl);
   $('#step-2 li').toggleClass('selected');
  });
  return promise;
}


function step3() {
  var promise = $.Deferred(),
      cookies = bakeCookies();
  if (cookies.username && cookies.access_token) {
    token = localStorage.token = cookies.access_token;
    username = localStorage.username = cookies.username;
    $.post('/queue', {queue: pushUrl});

    // Clear the token and username.
    var date = new Date();
    date.setTime(date.getTime() - (24 * 60 * 60 * 1000));
    var expires = '; expires=' + date.toGMTString() + ';';
    document.cookie = 'username=;' + expires;
    document.cookie = 'access_token=;' + expires;
    promise.resolve();
  } else if (localStorage.username && localStorage.token) {
    token = localStorage.token;
    username = localStorage.username;
    promise.resolve();
  }
  return promise;
}


function step4() {
  $(document).trigger('step', [3]);
  var promise = getUserData();
  promise.pipe(fetchRepos).then(render).then(addOrgRepos);
}


function render() {
  var hooks = getHooks(),
      allRepos = repos.concat(orgRepos);
  for (idx in allRepos) {
    allRepos[idx].hasHook = (allRepos[idx].id in hooks);
  }
  $('#repos').html(Mustache.render($('#repos-template').text(),
                   {data: [{name: 'User Repos',
                            exists: !!repos,
                            repos: repos},
                           {name: 'Org Repos',
                            exists: !!orgRepos,
                            repos: orgRepos}]}));
}


$(document).bind('step', function(e, step) {
  var child = ':nth-child(' + step + ')';
  // jQuery's addClass/removeClass isn't playing nice with svg.
  $('.selected').each(function(idx, el) {
    if (el.classList)
      el.classList.remove('selected');
  })
  $('#omgsvg,#nav,#steps').children(child).each(function(idx, el) {
    if (el.classList)
      el.classList.add('selected');
  });
});

$(document).ready(main);
