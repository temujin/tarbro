import exceptions
import json
import os
from multiprocessing import Process
import sys
import tarfile
import time

import humanfriendly as hf
import redis

sys.path.append(os.path.join(os.path.split(__file__)[0]))

from SETTINGS import *



HTML_PRE = """
<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 3.2 Final//EN\">
<html>
<head>
<title>Index of {path}</title>
</head>
<body>
<h1>Index of {path}</h1>
<pre><hr><img src=\"/icons/back.gif\" alt=\"[PARENTDIR]\"> <a href=\"{parent}\">Parent Directory</a>

<table style=\"white-space:nowrap;\">
<th style=\"text-align: left;\">Name</th>
<th style=\"text-align: center;\">Last modified</th>
<th style=\"text-align: left;\">Size</th>
"""

HTML_FOLDER = "<tr><td><img src=\"/icons/folder.gif\" alt=\"[DIR]\"> <a href=\"{href}\">{name}/</a></td> <td style=\"padding: 0 50px 0 50px\">{mtime}</td> <td>-</td></tr>"
HTML_FILE = "<tr><td><img src=\"/icons/generic.gif\" alt=\"[FILE]\"> <a href=\"{href}\">{name}</a></td> <td style=\"padding: 0 50px 0 50px\">{mtime}</td> <td>{size}</td></tr>"
HTML_LINK = "<tr><td><img src=\"/icons/link.gif\" alt=\"[SYMLINK]\">{name} -> {linkpath}</td> <td>{mtime}</td> <td style=\"padding: 0 50px 0 50px\">-</td></tr>"

HTML_POST = """
</table>
<hr></pre>
</body></html>
"""


def ttype(tobj):
    """Represent fs element type
    One of directory, file or link
    :param tobj: result of tarfile.getmember()
    :return: filesystem element one char representation
    """

    if tobj.isdir():
        return "d"
    elif tobj.isreg():
        return "f"
    elif tobj.issym():
        return "l"


def build_cache_worker(environ, in_tar_path=None, tfo=None):
    """Gether and cache tar filesystem object(s) data

    :param environ: http request environ object
    :param in_tar_path: internal tar path of fs element to process.
                        If is None - all elements of tar  processed
    :param tfo: open tarfile object.
                If is None - new one will be created
    """
    req_path = environ["PATH_INFO"]
    redis_cli = redis.StrictRedis()
    tfile = environ["PATH_TRANSLATED"]

    tf = tfo if tfo is not None else tarfile.open(tfile)

    fullist = tf.getnames()
    for_members = [in_tar_path] if in_tar_path is not None else fullist

    for name in for_members:
        if name:
            tarobj = tf.getmember(name)
            ftype = ttype(tarobj)
        else:
            # assume it's a root of tar
            ftype = "d"

        meta = {}

        meta["type"] = ftype
        if ftype == "d":
            meta["content"] = {}
            for path in fullist:
                if not path.startswith(name):
                    continue
                cutpath = path.replace(name, "")
                spath = cutpath.split(os.path.sep)
                if not spath[0]:
                    spath.pop(0)
                if len(spath) != 1 or not spath[0]:
                    continue
                dto = tf.getmember(path)

                meta["content"][spath[0]] = {
                    "type": ttype(dto),
                    "mtime": time.strftime(
                        "%Y-%m-%d %H:%M",
                        time.gmtime(dto.mtime)),
                    "size": hf.format_size(dto.size)
                }

        json_meta = json.dumps(meta)
        redis_cli.setex("{}?{}".format(req_path, name), CACHE_TTL, json_meta)

    if tfo is None:
        tf.close()


def start_build_cache(environ):
    """Run build_cache_worker in separate process
    Non blocking way to build cache for the whole tar

    :param environ: http reques environ object
    """
    p = Process(target=build_cache_worker, args=(environ,))
    p.daemon = True
    p.start()


def get_cached(environ, redis_cli, in_tar_path=None, tfo=None):
    """Lazy cache

    :param environ: http reques environ object
    :param redis_cli: instantiated redis client
    :param in_tar_path: internal tar path of fs object to get
                        if is None "PATH_INFO" from environ will be used
    :param tfo: open tarfile object
    :return: cdict
    """
    cached_info = redis_cli.get("{}?{}".format(
        environ["PATH_INFO"], in_tar_path or environ["QUERY_STRING"]))

    if cached_info is None:
        build_cache_worker(environ, in_tar_path=in_tar_path, tfo=tfo)
        cached_info = redis_cli.get("{}?{}".format(
            environ["PATH_INFO"], in_tar_path or environ["QUERY_STRING"]))

    return json.loads(cached_info)


def get_tar_list(environ, redis_cli, start_response, tfo=None):
    """List directory in tar
    Produses HTML, representing directory list.

    :param environ: environmennt, provided by http server (Apache2)
    :param redis_cli: instantiated redis client
    :param star_response: callback, provided by 'mod_wsgi'
    :param tfo: open tarfile object
    """

    in_tar_path = environ["QUERY_STRING"]
    redis_key = environ["REQUEST_URI"]

    res = get_cached(environ, redis_cli, in_tar_path, tfo)["content"]

    # part of request after port number
    request_uri = redis_key

    # generate parent path for related link
    srequri = request_uri.split("?")
    if len(srequri) > 1 and srequri[1]:
        parent_dir = "?".join([srequri[0], os.path.split(srequri[1])[0]])
    else:
        parent_dir = os.path.split(srequri[0])[0]
    if parent_dir.endswith("?"):
        parent_dir = parent_dir[:-1]

    folders = []
    files = []

    delim = "/" if in_tar_path else "?"

    html_lines = [HTML_PRE.format(path=request_uri, parent=parent_dir)]

    for key in sorted(res):
        if res[key]["type"] == "d":
            folders.append(
                HTML_FOLDER.format(
                    name=key,
                    mtime=res[key]["mtime"],
                    href="{}{}{}".format(request_uri, delim, key)))
        elif res[key]["type"] == "f":
            files.append(
                HTML_FILE.format(
                    name=key,
                    mtime=res[key]["mtime"],
                    size=res[key]["size"],
                    href="{}{}{}".format(request_uri, delim, key)))
        else:
            files.append(
                HTML_LINK.format(
                    name=key,
                    mtime=res[key]["mtime"],
                    linkpath=res[key]["linkpath"]))

    html_lines.extend(folders)
    html_lines.extend(files)
    html_lines.extend(HTML_POST)

    status = "200 OK"

    response_headers = [('Content-type', 'text/html')]
    start_response(status, response_headers)
    tfo.close()
    return html_lines


def get_path_type(environ, redis_cli, tfo):
    """Dtermine path type in tarfile, query references to

    :param environ: request environ object
    :param redis_cli: instantiated redis client
    :param tfo: opened tarfile object
    """

    in_tar_path = environ["QUERY_STRING"]

    if not in_tar_path:
        # assume it's a root of tar
        return "d"

    return get_cached(environ, redis_cli, in_tar_path, tfo)["type"]


def get_file(in_tar_path, start_response, tfo):
    """Print file if text else download

    :param in_tar_path: internal tar path to file
    :param start_response: callback, provided by 'mod_wsgi'
    :param tfo: open tarfile object
    """
    status = "200 OK"

    filobj = tfo.extractfile(in_tar_path)
    testline = filobj.read(size=40)
    try:
        testline.decode("utf-8")
        filobj.seek(0)
        response_headers = [('Content-type', 'text/plain'),
                            ('Content-Disposition', 'filename={}'.format(
                                os.path.split(in_tar_path)[1]))]
    except UnicodeDecodeError:
        response_headers = [('Content-type',
                             'application/octet-stream'),
                            ('Content-Disposition',
                             'attachment; filename={}'.format(
                                 os.path.split(in_tar_path)[1]))]

    start_response(status, response_headers)
    while True:
        buf = filobj.read(256)
        if buf:
            yield buf
        else:
            tfo.close()
            raise exceptions.StopIteration()


def application(environ, start_response):
    """WSGI entry point

    :param environ: provided by 'mod_wsgi'
    :param start_response: callback, provided by 'mod_wsgi'
    """

    # part of query after '?'
    query_string = environ["QUERY_STRING"]

    # absolut path of tarfile on file system (depends on DOCUMENT_ROOT)
    tar_path = environ["PATH_TRANSLATED"]

    req_path = environ["PATH_INFO"]
    redis_cli = redis.StrictRedis(**REDIS_CONN_ARGS)
    if not redis_cli.keys("{}*".format(req_path)):
        start_build_cache(environ)

    tfo = tarfile.open(tar_path, "r")
    try:
        ftype = get_path_type(environ, redis_cli, tfo)
    except exceptions.KeyError as e:
        start_response("404 Not found", [])
        return str(e)

    # we're  not  processing links, so, just list the directory link in
    if ftype == "l":
        query_string = os.path.split(query_string)
        ftype = "d"

    if ftype == "d":
        return get_tar_list(environ, redis_cli, start_response, tfo)
    else:
        return get_file(query_string, start_response, tfo)
