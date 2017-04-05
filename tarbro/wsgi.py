import exceptions
import tarfile
import time

import humanfriendly as hf
import os

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


def get_tar_list(environ, tfile, start_response, path=""):
    """List directory in tar

    :param environ: environmennt, provided by http server (Apache2)
    :param tfile: path to tarfile on file system
    :param path: path in tarfile
    """
    with tarfile.open(tfile) as tf:
        fulllist = tf.getnames()

        # part of request after port number
        request_uri = environ["REQUEST_URI"]

        # generate parent path for related link
        srequri = request_uri.split("?")
        if len(srequri) > 1 and srequri[1]:
            parent_dir = "?".join([srequri[0], os.path.split(srequri[1])[0]])
        else:
            parent_dir = os.path.split(srequri[0])[0]
        if parent_dir.endswith("?"):
            parent_dir = parent_dir[:-1]

        res = {}

        for line in fulllist:

            # manipulations, to list oly items in path

            # split line by os separator
            sname = filter(None, line.strip().split(os.path.sep))
            # split path by os separator
            spath = filter(None, path.strip().split(os.path.sep))

            # if current line represents object not in from path - continue
            if not sname[:len(spath)] == spath:
                continue

            if len(sname) <= len(spath):
                continue

            # cat path form line
            shrinked = sname[len(spath):]
            # get only first element, cause it's exactly in the path
            name = shrinked[0]

            if name not in res:
                ftype = get_path_type(tfile, os.path.join(path, name),
                                      tfile_obj=tf)
                tarobj = tf.getmember(os.path.join(path, name))

                # modification time
                mtime = time.strftime("%Y-%m-%d %H:%M",
                                      time.gmtime(tarobj.mtime))
                # size
                fsize = tarobj.size

                res[name] = {"type": ftype,
                             "mtime": mtime,
                             "size": hf.format_size(fsize),
                             "linkpath": tarobj.linkpath}

    folders = []
    files = []

    delim = "/" if path else "?"

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
    html_lines.extend(HTML_FILE.format('Download this whole tar.gz file',
                                       mtime=somehow_get_mtime_of_tfile(),
                                       size=somehow_get_size_of_tfile(),
                                       href="{}{}{}".format(request_uri, '?', 'TARBRO_DOWNLOAD')))
    html_lines.extend(HTML_POST)

    status = "200 OK"

    response_headers = [('Content-type', 'text/html')]
    start_response(status, response_headers)
    return html_lines


def get_path_type(tfile, path=None, tfile_obj=None):
    """Dtermine path type in tarfile, query references to

    :param tfile: path to tarfile on file system
    :param path: path in tarfile
    :param tfile_obj: opened tarfile object
    """

    # empty path always points to root of tar, which is of type 'directory'
    if not path:
        return "d"

    tf = tfile_obj or tarfile.open(tfile)

    tarobj = tf.getmember(path)
    if tarobj.isdir():
        return "d"
    elif tarobj.isreg():
        return "f"
    elif tarobj.issym():
        return "l"

    if tfile_obj is None:
        tf.close()


def get_file(tfile, fullpath, start_response):
    """Print file if text else download

    :param tfile: path to tarfile on file system
    :param fullpath: full file path in tarfile
    """
    status = "200 OK"
    with tarfile.open(tfile) as tf:
        filobj = tf.extractfile(fullpath)
        testline = filobj.read(size=40)
        try:
            testline.decode("utf-8")
            filobj.seek(0)
            response_headers = [('Content-type', 'text/plain'),
                                ('Content-Disposition', 'filename={}'.format(
                                    os.path.split(fullpath)[1]))]
        except UnicodeDecodeError:
            response_headers = [('Content-type',
                                 'application/octet-stream'),
                                ('Content-Disposition',
                                 'attachment; filename={}'.format(
                                     os.path.split(fullpath)[1]))]

        start_response(status, response_headers)
        while True:
            buf = filobj.read(256)
            if buf:
                yield buf
            else:
                raise exceptions.StopIteration()


def application(environ, start_response):
    """WSGI entry point

    environ is provided by http server (Apache2)
    """

    # part of query after '?'
    query_string = environ["QUERY_STRING"]

    # absolut path of tarfile on file system (depends on DOCUMENT_ROOT)
    tar_path = environ["PATH_TRANSLATED"]

    if query_string = 'TARBRO_DOWNLOAD':
        return  # or some other way how to send the file as whole
    
    ftype = get_path_type(tar_path, query_string)

    # we're  not  processing links, so, just list the directory link in
    if ftype == "l":
        query_string = os.path.split(query_string)
        ftype = "d"

    if ftype == "d":
        return get_tar_list(environ, tar_path, start_response,
                            path=query_string)
    else:
        return get_file(tar_path, query_string, start_response)
