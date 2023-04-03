#!/usr/bin/env -S python3 -u
"""
ADOdb release upload script.

Uploads release zip/tarball files generated by buildrelease.py to SourceForge.

This file is part of ADOdb, a Database Abstraction Layer library for PHP.

@package ADOdb
@link https://adodb.org Project's web site and documentation
@link https://github.com/ADOdb/ADOdb Source code and issue tracker

The ADOdb Library is dual-licensed, released under both the BSD 3-Clause
and the GNU Lesser General Public Licence (LGPL) v2.1 or, at your option,
any later version. This means you can use it in proprietary products.
See the LICENSE.md file distributed with this source code for details.
@license BSD-3-Clause
@license LGPL-2.1-or-later

@copyright 2014 Damien Regad, Mark Newnham and the ADOdb community
@author Damien Regad
"""

import getopt
import getpass
import glob
import json
import os
from os import path
import re
import requests
import subprocess
import sys

from adodbutil import env


# Directories and files to exclude from release tarballs
# for debugging, set to a local dir e.g. "localhost:/tmp/sf-adodb/"

sf_files = "frs.sourceforge.net:/home/frs/project/adodb/"

# SourceForge Release API base URL
# https://sourceforge.net/p/forge/documentation/Using%20the%20Release%20API/
sf_api_url = 'https://sourceforge.net/projects/adodb/files/{}/'

# rsync command template
rsync_cmd = "rsync -vP --rsh ssh {opt} {src} {usr}@{dst}"

# Command-line options
options = "hu:ns"
long_options = ["help", "user=", "dry-run", "skip-upload"]

# Global flags
dry_run = False
username = getpass.getuser()
release_path = ''
skip_upload = False


def usage():
    """
    Print script's command-line arguments help.
    """
    print('''Usage: {} [options] username [release_path]

    This script will upload the files in the given directory (or the
    current one if unspecified) to SourceForge.

    Parameters:
        release_path            Location of the release files to upload,
                                see buildrelease.py to generate them.
                                Defaults to current directory.

    Options:
        -h | --help             Show this usage message
        -u | --user <name>      SourceForge account (defaults to current user)
        -s | --skip-upload      Do not upload the release files (allows only
                                updating previously uploaded files information)
        -n | --dry-run          Do not upload or update sourceforge
'''.format(
        path.basename(__file__)
    ))
# end usage()


def call_rsync(usr, opt, src, dst):
    """
    Call rsync to upload files with given parameters.

    :param usr: ssh username
    :param opt: options
    :param src: source directory
    :param dst: target directory
    """
    global dry_run

    command = rsync_cmd.format(usr=usr, opt=opt, src=src, dst=dst)

    # Create directory if it does not exist
    dst_split = dst.rsplit(':')
    host = dst_split[0]
    dst = dst_split[1]
    mkdir = 'ssh {usr}@{host} mkdir -p {dst}'.format(
        usr=usr,
        host=host,
        dst=dst
    )

    if dry_run:
        print(mkdir)
        print(command)
    else:
        subprocess.call(mkdir, shell=True)
        subprocess.call(command, shell=True)


def get_release_version():
    """
    Return the version number (X.Y.Z) from the zip file to upload,
    excluding the SemVer suffix.
    """
    try:
        zipfile = glob.glob('adodb-*.zip')[0]
    except IndexError:
        print("ERROR: release zip file not found in '{}'".format(release_path))
        sys.exit(1)

    try:
        version = re.search(
            r"^adodb-([\d]+\.[\d]+\.[\d]+)(-(alpha|beta|rc)\.[\d]+)?\.zip$",
            zipfile
            ).group(1)
    except AttributeError:
        print('''ERROR: unable to extract version number from '{}'
       Only 3 groups of digits separated by periods are allowed'''
              .format(zipfile))
        sys.exit(1)

    return version


def sourceforge_target_dir(version):
    """
    Return the SourceForge target directory.

    This is relative to the root defined in sf_files global variable:
    basedir/subdir, with
    - basedir:
      - for ADOdb version 5: adodb-php5-only
      - for newer versions:  adodbX (where X is the major version number)
    - subdir:
      - if version >= 5.21: adodb-X.Y
      - for older versions: adodb-XYZ-for-php5
    """
    major_version = int(version.rsplit('.')[0])

    # Base directory
    if major_version == 5:
        directory = 'adodb-php5-only/'
    else:
        directory = 'adodb{}/'.format(major_version)

    # Keep only X.Y (discard patch number and pre-release suffix)
    short_version = version.split('-')[0].rsplit('.', 1)[0]

    directory += "adodb-" + short_version

    return directory


def process_command_line():
    """
    Retrieve command-line options and set global variables accordingly.
    """
    global dry_run, username, release_path, skip_upload

    # Get command-line options
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], options, long_options)
    except getopt.GetoptError as err:
        print(str(err))
        usage()
        sys.exit(2)

    # Default values for flags
    username = getpass.getuser()

    for opt, val in opts:
        if opt in ("-h", "--help"):
            usage()
            sys.exit(0)

        elif opt in ("-u", "--user"):
            username = val

        elif opt in ("-s", "--skip-upload"):
            skip_upload = True

        elif opt in ("-n", "--dry-run"):
            print("Dry-run mode - files will not be uploaded or modified")
            dry_run = True

    # Mandatory parameters
    # (none)

    # Change to release directory, current if not specified
    try:
        release_path = args[0]
        os.chdir(release_path)
    except IndexError:
        release_path = os.getcwd()


def upload_release_files():
    """
    Upload release files from source directory to SourceForge.
    """
    version = get_release_version()
    target = sf_files + sourceforge_target_dir(version)

    print()
    print("Uploading release files...")
    print("  Source:", release_path)
    print("  Target: " + target)
    print("  Files:  " + ', '.join(glob.glob('*')))
    print()
    call_rsync(
        username,
        "",
        path.join(release_path, "*"),
        target
    )
    print()


def set_sourceforge_file_info():
    global dry_run

    print("Updating uploaded files information")

    base_url = sf_api_url.format(
        sourceforge_target_dir(get_release_version())
        )
    headers = {'Accept': 'application/json"'}

    # Loop through uploaded files
    for file in glob.glob('adodb-*'):
        print("  " + file)

        # Determine defaults based on file extension
        ext = path.splitext(file)[1]
        if ext == '.zip':
            defaults = ['windows']
        elif ext == '.gz':
            defaults = ['linux', 'mac', 'bsd', 'solaris', 'others']
        else:
            print("WARNING: Unknown extension for file", file)
            continue

        # SourceForge API request
        url = path.join(base_url, file)
        payload = {
            'default': defaults,
            'api_key': env.sf_api_key
            }
        if dry_run:
            req = requests.Request('PUT', url, headers=headers, params=payload)
            r = req.prepare()
            print("    Calling SourceForge Release API:", r.url)
        else:
            req = requests.put(url, headers=headers, params=payload)

            # Print results
            if req.status_code == requests.codes.ok:
                result = json.loads(req.text)['result']
                print("    Download default for:", result['x_sf']['default'])
            else:
                if req.status_code == requests.codes.unauthorized:
                    err = "access denied"
                else:
                    err = "SourceForge API call failed"
                print("ERROR: {} - check API key".format(err))
                break


def main():
    # Start upload process
    print("ADOdb release upload script")

    process_command_line()

    global skip_upload
    if skip_upload:
        print("Skipping upload of release files")
    else:
        upload_release_files()

    set_sourceforge_file_info()

# end main()


if __name__ == "__main__":
    main()
