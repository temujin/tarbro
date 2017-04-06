Tarbro
======

mod_wsgi application for browsing tarballs' content without unpacking them.


Purposes
--------

CI systems produces huge amount of logs. It's important to have online access to this logs for analyzing.

Current application is developed for case, when your CI produces logs tarballs.

With **tarbro** you can host tarballs and browse their content online without unpacking.


Features
--------

* Browse tarballs in manner, `Apache2` browses directories.

* Stateless. Sessionless. You can distribude links, that reference to object in tarball.

* View text files' content from tarball in browser.

* Download files, that were not determined as text files.



Requirements
------------

* Apache2

* mod_wsgi

* redis server

Installation
------------

Clone this repo

.. code-block:: console

  git clone https://github.com/rgel/tarbro.git

Create and activate virtualenv

.. code-block:: console

  cd tarbro
  virtualenv .venv
  source .venv/bin/activate

Install required pip packages

.. code-block:: console

  pip install -U pip && pip install -r requirements

Copy sample site configuration file to httpd configuration directory:

.. code-block:: console

  cp samples/apache-virthost.conf.sample /etc/httpd/conf.d/tarbro.conf

and update next lines with actual data:

    *   ``Define tarbro_path /opt/tarbro``

    *   ``Define document_root /srv/static``

    *   ``WSGIPythonHome ${tarbro_path}/.venv``

    *   ``<VirtualHost *:80>``

Update SETTINGS.py if you need