#!/bin/bash -ex

dir_parent=$(cd $(dirname $0); pwd)

wget https://raw.githubusercontent.com/tom-gall/android-qa-classifier-data/master/flakey.txt -O /tmp/flakey.txt
${dir_parent}/../workspace-python3/bin/python ${dir_parent}/manage.py kernelreport EAP510 /tmp/kernelreport.txt /tmp/flakey.txt No
