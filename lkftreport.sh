#!/bin/bash -ex

dir_parent=$(cd $(dirname $0); pwd)
# need to be run with "sudo -u www-data ./lkftreport.sh" on production environment
${dir_parent}/../workspace-python3/bin/python ${dir_parent}/manage.py lkftreport "$@"
