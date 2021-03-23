## https://docs.djangoproject.com/en/1.11/topics/db/managers/
## https://docs.djangoproject.com/en/dev/howto/custom-management-commands/#howto-custom-management-commands
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-1-62d6b6dc24f8
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-2-fc1fb810b81d
## https://medium.com/@kevin.michael.horan/scheduling-tasks-in-django-with-the-advanced-python-scheduler-663f17e868e6
## https://django-background-tasks.readthedocs.io/en/latest/
# VtsKernelLinuxKselftest#timers_set-timer-lat_32bit
import pdb
import datetime
import json
import os
import re
import yaml
from dateutil import parser
import datetime
import subprocess

from django.core.management.base import BaseCommand, CommandError

from django.utils.timesince import timesince

from lkft.models import KernelChange, CiBuild, ReportBuild

from lcr import qa_report

from lcr.settings import QA_REPORT, QA_REPORT_DEFAULT, BUILD_WITH_JOBS_NUMBER

from lkft.views import get_test_result_number_for_build, get_lkft_build_status, get_classified_jobs
from lkft.views import extract
from lkft.views import get_result_file_path
from lkft.views import download_attachments_save_result
from lkft.lkft_config import get_version_from_pname, get_kver_with_pname_env

qa_report_def = QA_REPORT[QA_REPORT_DEFAULT]
qa_report_api = qa_report.QAReportApi(qa_report_def.get('domain'), qa_report_def.get('token'))
jenkins_api = qa_report.JenkinsApi('ci.linaro.org', None)

rawkernels = {
   '4.4':[
            '4.4p-10.0-gsi-hikey',
            '4.4p-9.0-hikey',
            '4.4o-10.0-gsi-hikey',
            '4.4o-9.0-lcr-hikey',
            '4.4o-8.1-hikey',
            ],
   '4.9':[ 
            '4.9q-10.0-gsi-hikey960',
            '4.9q-10.0-gsi-hikey',
            '4.9p-10.0-gsi-hikey960',
            '4.9p-10.0-gsi-hikey',
            '4.9o-10.0-gsi-hikey960',
            '4.9p-9.0-hikey960',
            '4.9p-9.0-hikey',
            '4.9o-10.0-gsi-hikey',
            '4.9o-9.0-lcr-hikey',
            '4.9o-8.1-hikey', 
            ],
   '4.14':[ 
            '4.14-stable-master-hikey960-lkft',
            '4.14-stable-master-hikey-lkft',
            '4.14-stable-aosp-x15',
            '4.14q-10.0-gsi-hikey960',
            '4.14q-10.0-gsi-hikey',
            '4.14p-10.0-gsi-hikey960',
            '4.14p-10.0-gsi-hikey',
            '4.14p-9.0-hikey960',
            '4.14p-9.0-hikey',
            ],
   '4.19':[ 
            '4.19q-10.0-gsi-hikey960',
            '4.19q-10.0-gsi-hikey',
            '4.19-stable-aosp-x15',
            ],
   '5.4':[ 
            '5.4-gki-aosp-master-db845c',
            '5.4-gki-aosp-master-hikey960',
            '5.4-aosp-master-x15',
            '5.4-lts-gki-android11-android11-hikey960',
            '5.4-lts-gki-android11-android11-db845c',
            '5.4-gki-android11-android11-hikey960',
            '5.4-gki-android11-android11-db845c',
            ],
   '5.10':[ 
            '5.10-gki-aosp-master-db845c',
            '5.10-gki-aosp-master-hikey960',
            ],
   'EAP510':[ 
            '5.10-gki-private-android12-db845c',
            '5.10-gki-private-android12-hikey960',
            ],
   'EAP54':[ 
            '5.4-gki-private-android12-db845c',
            '5.4-gki-private-android12-hikey960',
            ],
}

projectids = {
   '4.4o-8.1-hikey': 
                    {'project_id': 86, 
                     'hardware': 'HiKey',
                     'OS' : 'LCR-Android8',
                     'baseOS' : 'Android8',
                     'kern' : '4.4',
                     'branch' : 'Android-4.4-o',}, 
   '4.4o-9.0-lcr-hikey':
                    {'project_id': 253, 
                     'hardware': 'HiKey',
                     'OS' : 'LCR-Android9',
                     'baseOS' : 'Android9',
                     'kern' : '4.4',
                     'branch' : 'Android-4.4-o',},
   '4.4o-10.0-gsi-hikey':
                    {'project_id': 254, 
                     'hardware': 'HiKey',
                     'OS' : 'Android10',
                     'kern' : '4.4',
                     'branch' : 'Android-4.4-o',},
   '4.4p-9.0-hikey':
                    {'project_id': 123, 
                     'hardware': 'HiKey',
                     'OS' : 'LCR-Android9',
                     'baseOS' : 'Android9',
                     'kern' : '4.4',
                     'branch' : 'Android-4.4-p',},
   '4.4p-10.0-gsi-hikey':
                    {'project_id': 225, 
                     'hardware': 'HiKey',
                     'OS' : 'Android10',
                     'kern' : '4.4',
                     'branch' : 'Android-4.4-p',},
   '4.9o-8.1-hikey':
                    {'project_id': 87, 
                     'hardware': 'HiKey',
                     'OS' : 'LCR-Android8',
                     'baseOS' : 'Android8',
                     'kern' : '4.9',
                     'branch' : 'Android-4.9-o',},
   '4.9o-9.0-lcr-hikey':
                    {'project_id': 250, 
                     'hardware': 'HiKey',
                     'OS' : 'LCR-Android9',
                     'baseOS' : 'Android9',
                     'kern' : '4.9',
                     'branch' : 'Android-4.9-o',},
   '4.9o-10.0-gsi-hikey':
                    {'project_id': 251, 
                     'hardware': 'HiKey',
                     'OS' : 'Android10',
                     'kern' : '4.9',
                     'branch' : 'Android-4.9-o',},
   '4.9o-10.0-gsi-hikey960':
                    {'project_id': 255, 
                     'hardware': 'HiKey960',
                     'OS' : 'Android10',
                     'kern' : '4.9',
                     'branch' : 'Android-4.9-o',},
   '4.9p-9.0-hikey':
                    {'project_id': 122, 
                     'hardware': 'HiKey',
                     'OS' : 'LCR-Android9',
                     'baseOS' : 'Android9',
                     'kern' : '4.9',
                     'branch' : 'Android-4.9-p',},
   '4.9p-9.0-hikey960':
                    {'project_id': 179,
                     'hardware': 'HiKey960',
                     'OS' : 'LCR-Android9',
                     'baseOS' : 'Android9',
                     'kern' : '4.9',
                     'branch' : 'Android-4.9-p',},
   '4.9p-10.0-gsi-hikey':
                    {'project_id': 223,
                     'hardware': 'HiKey',
                     'OS' : 'Android10',
                     'kern' : '4.9',
                     'branch' : 'Android-4.9-p',},
   '4.9p-10.0-gsi-hikey960':
                    {'project_id': 222, 
                     'hardware': 'HiKey960',
                     'OS' : 'Android10',
                     'kern' : '4.9',
                     'branch' : 'Android-4.9-p',},
   '4.9q-10.0-gsi-hikey':
                    {'project_id': 212, 
                     'hardware': 'HiKey',
                     'OS' : 'Android10',
                     'kern' : '4.9',
                     'branch' : 'Android-4.9-q',},
   '4.9q-10.0-gsi-hikey960':
                    {'project_id': 213, 
                     'hardware': 'HiKey960',
                     'OS' : 'Android10',
                     'kern' : '4.9',
                     'branch' : 'Android-4.9-q',},
   '4.14p-9.0-hikey':
                    {'project_id': 121, 
                     'hardware': 'HiKey',
                     'OS' : 'LCR-Android9',
                     'baseOS' : 'Android9',
                     'kern' : '4.14',
                     'branch' : 'Android-4.14-p',},
   '4.14p-9.0-hikey960':
                    {'project_id': 177, 
                     'hardware': 'HiKey960',
                     'OS' : 'LCR-Android9',
                     'baseOS' : 'Android9',
                     'kern' : '4.14',
                     'branch' : 'Android-4.14-p',},
   '4.14p-10.0-gsi-hikey':
                    {'project_id': 220, 
                     'hardware': 'HiKey',
                     'OS' : 'Android10',
                     'kern' : '4.14',
                     'branch' : 'Android-4.14-p',},
   '4.14p-10.0-gsi-hikey960':
                    {'project_id': 221, 
                     'hardware': 'HiKey960',
                     'OS' : 'Android10',
                     'kern' : '4.14',
                     'branch' : 'Android-4.14-p',},
   '4.14q-10.0-gsi-hikey':
                    {'project_id': 211, 
                     'hardware': 'HiKey',
                     'OS' : 'Android10',
                     'kern' : '4.14',
                     'branch': 'Android-4.14-q',},
   '4.14q-10.0-gsi-hikey960':
                    {'project_id': 214,
                     'hardware': 'HiKey960',
                     'OS' : 'Android10',
                     'kern' : '4.14',
                     'branch' : 'Android-4.14-q',},
   '4.14-stable-aosp-x15':
                    {'project_id': 320,
                     'hardware': 'X15',
                     'OS' : 'AOSP',
                     'kern' : '4.14',
                     'branch' : 'Android-4.14-stable',},
   '4.14-stable-master-hikey-lkft':
                    {'project_id': 297, 
                     'hardware': 'HiKey',
                     'OS' : 'AOSP',
                     'kern' : '4.14',
                     'branch': 'Android-4.14-stable',},
   '4.14-stable-master-hikey960-lkft':
                    {'project_id': 298, 
                     'hardware': 'HiKey960',
                     'OS' : 'AOSP',
                     'kern' : '4.14',
                     'branch': 'Android-4.14-stable',},
   '4.19q-10.0-gsi-hikey':
                    {'project_id': 210, 
                     'hardware': 'HiKey',
                     'OS' : 'Android10',
                     'kern' : '4.19',
                     'branch' : 'Android-4.19-q',},
   '4.19q-10.0-gsi-hikey960':
                    {'project_id': 215, 
                     'hardware': 'HiKey960',
                     'OS' : 'Android10',
                     'kern' : '4.19',
                     'branch' : 'Android-4.19-q',},
   '4.19-stable-aosp-x15':
                    {'project_id': 335, 
                     'hardware': 'x15',
                     'OS' : 'AOSP',
                     'kern' : '4.19',
                     'branch' : 'Android-4.19-stable',},
   '5.4-gki-aosp-master-hikey960':
                    {'project_id': 257, 
                     'hardware': 'HiKey960',
                     'OS' : 'AOSP',
                     'kern' : '5.4',
                     'branch' : 'Android-5.4',},
   '5.4-gki-aosp-master-db845c':
                    {'project_id': 261,
                     'hardware': 'db845',
                     'OS' : 'AOSP',
                     'kern' : '5.4',
                     'branch' : 'Android-5.4',},
   '5.4-aosp-master-x15':
                    {'project_id': 339,
                     'hardware': 'x15',
                     'OS' : 'AOSP',
                     'kern' : '5.4',
                     'branch' : 'Android-5.4',},
   '5.4-lts-gki-android11-android11-db845c':
                    {'project_id': 524,
                     'hardware': 'db845',
                     'OS' : 'Android11',
                     'kern' : '5.4',
                     'branch' : 'Android-5.4',},
   '5.4-lts-gki-android11-android11-hikey960':
                    {'project_id': 519,
                     'hardware': 'hikey960',
                     'OS' : 'Android11',
                     'kern' : '5.4',
                     'branch' : 'Android-5.4',},
   '5.4-gki-android11-android11-db845c':
                    {'project_id': 414,
                     'hardware': 'db845',
                     'OS' : 'Android11',
                     'kern' : '5.4',
                     'branch' : 'Android-5.4',},
   '5.4-gki-android11-android11-hikey960':
                    {'project_id': 409,
                     'hardware': 'hikey960',
                     'OS' : 'Android11',
                     'kern' : '5.4',
                     'branch' : 'Android-5.4',},
   '5.10-gki-aosp-master-hikey960':
                    {'project_id': 607, 
                     'hardware': 'HiKey960',
                     'OS' : 'AOSP',
                     'kern' : '5.10',
                     'branch' : 'Android-5.10',},
   '5.10-gki-aosp-master-db845c':
                    {'project_id': 606,
                     'hardware': 'db845',
                     'OS' : 'AOSP',
                     'kern' : '5.10',
                     'branch' : 'Android-5.10',},
   '5.10-gki-private-android12-db845c':
                    {'project_id': 617,
                     'hardware': 'db845',
                     'OS' : 'Android12',
                     'kern' : '5.10',
                     'branch' : 'Android-5.10',},
   '5.10-gki-private-android12-hikey960':
                    {'project_id': 616,
                     'hardware': 'HiKey960',
                     'OS' : 'Android12',
                     'kern' : '5.10',
                     'branch' : 'Android-5.10',},
   '5.4-gki-private-android12-db845c':
                    {'project_id': 620,
                     'hardware': 'db845',
                     'OS' : 'Android12',
                     'kern' : '5.4',
                     'branch' : 'Android-5.4',},
   '5.4-gki-private-android12-hikey960':
                    {'project_id': 621,
                     'hardware': 'HiKey960',
                     'OS' : 'Android12',
                     'kern' : '5.4',
                     'branch' : 'Android-5.4',},
}

def do_boilerplate(output):
    output.write("\n\nFailure Key:\n")
    output.write("--------------------\n")
    output.write("I == Investigation\nB == Bug#, link to bugzilla\nF == Flakey\nU == Unexpected Pass\n\n")

# a flake entry
# name, state, bugzilla
def process_flakey_file(flakefile):
    Dict44 = {'version' : 4.4 , 'flakelist' : [] }
    Dict49 = {'version' : 4.9 , 'flakelist' : [] }
    Dict414 = {'version' : 4.14, 'flakelist' : [] }
    Dict419 = {'version' : 4.19, 'flakelist' : [] }
    Dict54 = {'version' : 5.4, 'flakelist' : [] }
    Dict510 = {'version' : 5.10, 'flakelist' : [] }
    flakeDicts = [Dict44, Dict49, Dict414, Dict419, Dict54, Dict510]

    kernelsmatch = re.compile('[0-9]+.[0-9]+')
    androidmatch = re.compile('ANDROID[0-9]+|AOSP')
    hardwarematch = re.compile('HiKey|db845|HiKey960')
    allmatch = re.compile('ALL')
    #pdb.set_trace()
    Lines = flakefile.readlines()
    for Line in Lines:
        newstate = ' '
        if Line[0] == '#':
            continue
        if Line[0] == 'I' or Line[0] == 'F' or Line[0] == 'B' or Line[0] == 'E':
            newstate = Line[0]
            Line = Line[2:]
        m = Line.find(' ')
        if m:
            testname = Line[0:m]
            Line = Line[m:]
            testentry = {'name' : testname, 'state': newstate, 'board': [], 'androidrel':[] }
            if Line[0:4] == ' ALL':
               Line = Line[5:]
               Dict44['flakelist'].append(testentry)
               Dict49['flakelist'].append(testentry)
               Dict414['flakelist'].append(testentry)
               Dict419['flakelist'].append(testentry)
               Dict54['flakelist'].append(testentry)
               Dict510['flakelist'].append(testentry)
            else:
               n = kernelsmatch.match(Line)
               if n:
                  Line = Line[n.end():]
                  for kernel in n:
                      for Dict in flakeDicts:
                          if kernel == Dict['version']:
                              Dict['flakelist'].append(testentry)
               else:
                   continue 
            if Line[0:3] == 'ALL':
               Line = Line[4:]
               testentry['board'].append("HiKey")
               testentry['board'].append("HiKey960")
               testentry['board'].append("db845")
            else:
               h = hardwarematch.findall(Line)
               if h:
                  for board in h:
                      testentry['board'].append(board)
               else:
                   continue
            a = allmatch.search(Line)
            if a:
               testentry['androidrel'].append('Android8')
               testentry['androidrel'].append('Android9')
               testentry['androidrel'].append('Android10')
               testentry['androidrel'].append('Android11')
               testentry['androidrel'].append('AOSP')
            else:
               a = androidmatch.findall(Line)
               if a:
                  for android in a:
                      testentry['androidrel'].append(android)
               else:
                   continue
        else:
            continue 
       
    return flakeDicts

# take the data dictionaries, the testcase name and ideally the list of failures
# and determine how to classify a test case. This might be a little slow espeically
# once linked into bugzilla
def classifyTest(flakeDicts, testcasename, hardware, kernel, android):
    for dict in flakeDicts:
        if dict['version'] == kernel:
            break
    #pdb.set_trace()
    foundboard = 0
    foundandroid = 0
    #if testcasename == 'VtsKernelLinuxKselftest.timers_set-timer-lat_64bit':
    #    pdb.set_trace()
    #if testcasename == 'android.webkit.cts.WebChromeClientTest#testOnJsBeforeUnloadIsCalled#arm64-v8a':
    #    pdb.set_trace()
    for flake in dict['flakelist']:
        if flake['name'] == testcasename:
            for board in flake['board'] :
                if board == hardware:
                    foundboard = 1
                    break
            for rel in flake['androidrel']:
                if rel == android:
                    foundandroid = 1
                    break
            if foundboard == 1 and foundandroid == 1:
                return flake['state']
            else:
                return 'I'
    return 'I'


def versiontoMME(versionString):
    versionDict = { 'Major':0,
                    'Minor':0,
                    'Extra':0, }

    if versionString.startswith('v'):
        versionString = versionString[1:]
    # print versionString
    tokens = re.split( r'[.-]', versionString)
    # print tokens
    if tokens[0].isnumeric() and tokens[1].isnumeric() and tokens[2].isnumeric():
        versionDict['Major'] = tokens[0]
        versionDict['Minor'] = tokens[1]
        versionDict['Extra'] = tokens[2]

    return versionDict

#     number_passed = 0
#    number_failed = 0
#    number_assumption_failure = 0
#    number_ignored = 0
#    number_total = 0
#    modules_done = 0
#    modules_total = 0
#    jobs_finished = 0
#    jobs_total = 0

def tallyNumbers(build, jobTransactionStatus):
    buildNumbers = build['numbers']
    if 'numbers' in jobTransactionStatus['vts-job']:
        buildNumbers['failed_number'] += jobTransactionStatus['vts-job']['numbers'].number_failed
        buildNumbers['passed_number'] += jobTransactionStatus['vts-job']['numbers'].number_passed
        buildNumbers['ignored_number'] += jobTransactionStatus['vts-job']['numbers'].number_ignored
        buildNumbers['assumption_failure'] += jobTransactionStatus['vts-job']['numbers'].number_assumption_failure
        buildNumbers['total_number'] += jobTransactionStatus['vts-job']['numbers'].number_total
        buildNumbers['modules_done'] += jobTransactionStatus['vts-job']['numbers'].modules_done
        buildNumbers['modules_total'] += jobTransactionStatus['vts-job']['numbers'].modules_total
    else:
        if 'numbers' in jobTransactionStatus['vts-v7-job']:
            buildNumbers['failed_number'] += jobTransactionStatus['vts-v7-job']['numbers'].number_failed
            buildNumbers['passed_number'] += jobTransactionStatus['vts-v7-job']['numbers'].number_passed
            buildNumbers['ignored_number'] += jobTransactionStatus['vts-v7-job']['numbers'].number_ignored
            buildNumbers['assumption_failure'] += jobTransactionStatus['vts-v7-job']['numbers'].number_assumption_failure
            buildNumbers['total_number'] += jobTransactionStatus['vts-v7-job']['numbers'].number_total
            buildNumbers['modules_done'] += jobTransactionStatus['vts-v7-job']['numbers'].modules_done
            buildNumbers['modules_total'] += jobTransactionStatus['vts-v7-job']['numbers'].modules_total
        if jobTransactionStatus['vts-v8-job'] is not None:
            if 'numbers' in jobTransactionStatus['vts-v8-job']:
                buildNumbers['failed_number'] += jobTransactionStatus['vts-v8-job']['numbers'].number_failed
                buildNumbers['passed_number'] += jobTransactionStatus['vts-v8-job']['numbers'].number_passed
                buildNumbers['ignored_number'] += jobTransactionStatus['vts-v8-job']['numbers'].number_ignored
                buildNumbers['assumption_failure'] += jobTransactionStatus['vts-v8-job']['numbers'].number_assumption_failure
                buildNumbers['total_number'] += jobTransactionStatus['vts-v8-job']['numbers'].number_total
                buildNumbers['modules_done'] += jobTransactionStatus['vts-v8-job']['numbers'].modules_done
                buildNumbers['modules_total'] += jobTransactionStatus['vts-v8-job']['numbers'].modules_total

    if 'numbers' in jobTransactionStatus['cts-job']:
        buildNumbers['failed_number'] += jobTransactionStatus['cts-job']['numbers'].number_failed
        buildNumbers['passed_number'] += jobTransactionStatus['cts-job']['numbers'].number_passed
        buildNumbers['ignored_number'] += jobTransactionStatus['cts-job']['numbers'].number_ignored
        buildNumbers['assumption_failure'] += jobTransactionStatus['cts-job']['numbers'].number_assumption_failure
        buildNumbers['total_number'] += jobTransactionStatus['cts-job']['numbers'].number_total
        buildNumbers['modules_done'] += jobTransactionStatus['cts-job']['numbers'].modules_done
        buildNumbers['modules_total'] += jobTransactionStatus['cts-job']['numbers'].modules_total


def markjob(job, jobTransactionStatus):
    vtsSymbol = re.compile('-vts-')
    vtsv8Symbol = re.compile('-vts-kernel-arm64-v8a')
    vtsv7Symbol = re.compile('-vts-kernel-armeabi-v7a')
    bootSymbol = re.compile('boot')
    ctsSymbol = re.compile('-cts')

    vtsresult = vtsSymbol.search(job['name'])
    vtsv8result = vtsv8Symbol.search(job['name'])
    vtsv7result = vtsv7Symbol.search(job['name'])
    bootresult = bootSymbol.search(job['name'])
    ctsresult = ctsSymbol.search(job['name'])

    newjobTime = parser.parse(job['created_at'])

    if vtsv8result is not None: 
       jobTransactionStatus['vts-v8'] = 'true'
       # take the later of the two results
       if jobTransactionStatus['vts-v8-job'] is None:
           jobTransactionStatus['vts-v8-job'] = job
       else:
           origjobTime = parser.parse(jobTransactionStatus['vts-v8-job']['created_at'])
           if newjobTime > origjobTime :
               jobTransactionStatus['vts-v8-job'] = job
       if jobTransactionStatus['vts-v7'] == 'true':
           jobTransactionStatus['vts'] = 'true'

    if vtsv7result is not None: 
       jobTransactionStatus['vts-v7'] = 'true'
       # take the later of the two results
       if jobTransactionStatus['vts-v7-job'] is None:
           jobTransactionStatus['vts-v7-job'] = job
       else:
           origjobTime = parser.parse(jobTransactionStatus['vts-v7-job']['created_at'])
           if newjobTime > origjobTime :
               jobTransactionStatus['vts-v7-job'] = job
       if jobTransactionStatus['vts-v8'] == 'true':
           jobTransactionStatus['vts'] = 'true'

    if vtsresult is not None:
       jobTransactionStatus['vts'] = 'true'
       # take the later of the two results
       if jobTransactionStatus['vts-job'] is None:
           jobTransactionStatus['vts-job'] = job
       else:
           origjobTime = parser.parse(jobTransactionStatus['vts-job']['created_at'])
           if newjobTime > origjobTime :
               jobTransactionStatus['vts-job'] = job
    if ctsresult is not None :
       jobTransactionStatus['cts'] = 'true'
       # take the later of the two results
       if jobTransactionStatus['cts-job'] is None:
           jobTransactionStatus['cts-job'] = job
       else:
           origjobTime = parser.parse(jobTransactionStatus['cts-job']['created_at'])
           if newjobTime > origjobTime :
               jobTransactionStatus['cts-job'] = job
    if bootresult is not None :
       jobTransactionStatus['boot'] = 'true'
       # take the later of the two results
       if jobTransactionStatus['boot-job'] is None:
           jobTransactionStatus['boot-job'] = job
       else:
           origjobTime = parser.parse(jobTransactionStatus['boot-job']['created_at'])
           if newjobTime > origjobTime :
               jobTransactionStatus['boot-job'] = job


def find_best_two_runs(builds, project_name, project, exact):
    goodruns = []
    bailaftertwo = 0
    number_of_build_with_jobs = 0
    baseExactVersionDict=None
    nextVersionDict=None

    if exact!='No':
        baseExactVersionDict = versiontoMME(exact) 

    for build in builds:
        if bailaftertwo == 2:
            break
        build_number_passed = 0
        build_number_failed = 0
        build_number_total = 0
        build_modules_total = 0
        build_modules_done = 0
        build['created_at'] = qa_report_api.get_aware_datetime_from_str(build.get('created_at'))
        jobs = qa_report_api.get_jobs_for_build(build.get("id"))
        jobs_to_be_checked = get_classified_jobs(jobs=jobs).get('final_jobs')
        build_status = get_lkft_build_status(build, jobs_to_be_checked)
        #build_status = get_lkft_build_status(build, jobs)
        jobs=jobs_to_be_checked
        if build_status['has_unsubmitted']:
            #print "has unsubmitted"
            continue
        elif build_status['is_inprogress']:
            #print "in progress"
            continue
           
        # print "ok great should be complete" 
        '''
        if number_of_build_with_jobs < BUILD_WITH_JOBS_NUMBER:
            build_numbers = get_test_result_number_for_build(build, jobs)
            build_number_passed = build_number_passed + build_numbers.get('number_passed')
            build_number_failed = build_number_failed + build_numbers.get('number_failed')
            build_number_total = build_number_total + build_numbers.get('number_total')
            build_modules_total = build_modules_total + build_numbers.get('modules_total')
            build_modules_done = build_modules_done + build_numbers.get('modules_done')
            number_of_build_with_jobs = number_of_build_with_jobs + 1
            #print "numbers passed in build" + str(build_number_passed)
        number_of_build_with_jobs = number_of_build_with_jobs + 1
        build['numbers'] = {
                           'passed_number': build_number_passed,
                           'failed_number': build_number_failed,
                           'total_number': build_number_total,
                           'modules_done': build_modules_done,
                           'modules_total': build_modules_total,
                           }
        '''
        build['numbers'] = {
                           'passed_number': 0,
                           'failed_number': 0,
                           'ignored_number':0,
                           'assumption_failure':0,
                           'total_number': 0,
                           'modules_done': 0,
                           'modules_total': 0,
                           }
        build['jobs'] = jobs
        if not jobs:
            continue
        #if build_number_passed == 0:
        #    continue

        download_attachments_save_result(jobs=jobs)
            
        failures = {}
        resubmitted_job_urls = []
       
        jobisacceptable=1 
        jobTransactionStatus = { 'vts' : 'maybe', 'cts' : 'maybe', 'boot': 'maybe', 'vts-v7' : 'maybe', 'vts-v8' : 'maybe',
                                 'vts-job' : None, 'cts-job' : None, 'boot-job' : None, 'vts-v7-job': None, 'vts-v8-job': None }

        #pdb.set_trace()
        for job in jobs:
           ctsSymbol = re.compile('-cts')

           ctsresult = ctsSymbol.search(job['name'])
           jobstatus = job['job_status']
           jobfailure = job['failure']
           if ctsresult is not None:
               print("cts job" + str(jobfailure) + '\n')
           if jobstatus == 'Complete' and jobfailure is None :
              markjob(job, jobTransactionStatus)

           result_file_path = get_result_file_path(job=job)
           if not result_file_path or not os.path.exists(result_file_path):
              continue
           # now tally then move onto the next job
           kernel_version = get_kver_with_pname_env(prj_name=project_name, env=job.get('environment'))

           platform = job.get('environment').split('_')[0]
           metadata = {
              'job_id': job.get('job_id'),
              'qa_job_id': qa_report_api.get_qa_job_id_with_url(job_url=job.get('url')),
              'result_url': job.get('attachment_url'),
              'lava_nick': job.get('lava_config').get('nick'),
              'kernel_version': kernel_version,
              'platform': platform,
           }
           numbers = extract(result_file_path, failed_testcases_all=failures, metadata=metadata)
           job['numbers'] = numbers

        # now let's see what we have. Do we have a complete yet?
        print("vts: "+ jobTransactionStatus['vts'] + " cts: "+jobTransactionStatus['cts'] + " boot: " +jobTransactionStatus['boot'] +'\n')

        if jobTransactionStatus['vts'] == 'true' and jobTransactionStatus['cts'] == 'true':
           # and jobTransactionStatus['boot'] == 'true' :
           #pdb.set_trace()
           if bailaftertwo == 0 :
               baseVersionDict = versiontoMME(build['version'])
               if baseExactVersionDict is not None:
                   if baseVersionDict['Extra'] != baseExactVersionDict['Extra']:
                       continue
               # print "baseset"
           elif bailaftertwo == 1 :
               nextVersionDict = versiontoMME(build['version'])
               if nextVersionDict['Extra'] == baseVersionDict['Extra'] :
                   continue
           tallyNumbers(build, jobTransactionStatus)

           if nextVersionDict is not None:
               if int(nextVersionDict['Extra']) > int(baseVersionDict['Extra']):
                   goodruns.append(build)
               else:
                   goodruns.insert(0, build)
           else:
               goodruns.append(build)

           bailaftertwo += 1
        else:
           continue

        #if 'run_status' in build:
        #   # print "found run status" + "build " + str(build.get("id")) + " NOT selected"
        #    continue
        #else:
        #   # print "run status NOT found" + "build " + str(build.get("id")) + " selected"
        #   if bailaftertwo == 0 :
        #       baseVersionDict = versiontoMME(build['version'])
        #       # print "baseset"
        #   elif bailaftertwo == 1 :
        #       nextVersionDict = versiontoMME(build['version'])
        #       if nextVersionDict['Extra'] == baseVersionDict['Extra'] :
        #           continue
        #   goodruns.append(build)
        #   bailaftertwo += 1

        #pdb.set_trace()
        failures_list = []
        for module_name in sorted(failures.keys()):
            failures_in_module = failures.get(module_name)
            for test_name in sorted(failures_in_module.keys()):
                failure = failures_in_module.get(test_name)
                abi_stacktrace = failure.get('abi_stacktrace')
                abis = sorted(abi_stacktrace.keys())

                stacktrace_msg = ''
                if (len(abis) == 2) and (abi_stacktrace.get(abis[0]) != abi_stacktrace.get(abis[1])):
                    for abi in abis:
                        stacktrace_msg = '%s\n\n%s:\n%s' % (stacktrace_msg, abi, abi_stacktrace.get(abi))
                else:
                    stacktrace_msg = abi_stacktrace.get(abis[0])

                failure['abis'] = abis
                failure['stacktrace'] = stacktrace_msg.strip()
                failure['module_name'] = module_name
                failures_list.append(failure)

        #pdb.set_trace()
        android_version = get_version_from_pname(pname=project.get('name'))
        build['failures_list'] = failures_list

    return goodruns

    '''
              if jobstatus == 'Incomplete' :
        for job in jobs:
           pdb.set_trace()
           if job.get('job_status') is None and \
              job.get('submitted') and \
              not job.get('fetched'):
              job['job_status'] = 'Submitted'
              jobisaacceptable = 0

           if job.get('failure'):
              failure = job.get('failure')
              new_str = failure.replace('"', '\\"').replace('\'', '"')
              try:
                 failure_dict = json.loads(new_str)
              except ValueError:
                 failure_dict = {'error_msg': new_str}
           if job.get('parent_job'):
              resubmitted_job_urls.append(job.get('parent_job'))

           if job['job_status'] == 'Submitted':
              jobisacceptable = 0
           if jobisacceptable == 0:
              build['run_status'] = 'Submitted'

           # print "job " + job.get('job_id') + " " + job['job_status']

           result_file_path = get_result_file_path(job=job)
           if not result_file_path or not os.path.exists(result_file_path):
              continue
    '''


def find_regressions(goodruns):
    runA = goodruns[1]
    failuresA = runA['failures_list']
    runB = goodruns[0]
    failuresB = runB['failures_list']
    regressions = []
    for failureA in failuresA:
        match = 0
        for failureB in failuresB:
            testAname = failureA['test_name']
            testBname = failureB['test_name']
            if testAname == testBname:
                match = 1
                break
        if match != 1 :
            regressions.append(failureA)
    
    return regressions

def find_antiregressions(goodruns):
    runA = goodruns[1]
    failuresA = runA['failures_list']
    runB = goodruns[0]
    failuresB = runB['failures_list']
    antiregressions = []
    for failureB in failuresB:
        match = 0
        for failureA in failuresA:
            testAname = failureA['test_name']
            testBname = failureB['test_name']
            if testAname == testBname:
                match = 1
                break
        if match != 1 :
            antiregressions.append(failureB)
    
    return antiregressions


"""  Example project_info dict
                    {'project_id': 210, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.19-q',},
"""

def print_androidresultheader(output, project_info, run, priorrun ):
        output.write("    " + project_info['OS'] + "/" + project_info['hardware'] + " - " )
        output.write("Current:" + run['version'] + "  Prior:" + priorrun['version']+"\n")

def add_unique_kernel(unique_kernels, kernel_version, combo, unique_kernel_info):
    #pdb.set_trace()
    if kernel_version not in unique_kernels:
        unique_kernels.append(kernel_version)
        newlist = []
        newlist.append(combo)
        unique_kernel_info[kernel_version] = newlist
    else:
        kernellist= unique_kernel_info[kernel_version]
        kernellist.append(combo)


def report_results(output, run, regressions, combo, priorrun, flakes, antiregressions):
    jobs = run['jobs']
    job = jobs[0]
    #pdb.set_trace()
    numbers = run['numbers']
    project_info = projectids[combo]
    output.write(project_info['branch'] + "\n")
    print_androidresultheader(output, project_info, run, priorrun)
    #pdb.set_trace()
    output.write("    " + str(len(regressions)) + " Regressions ")
    output.write(str(numbers['failed_number']) + " Failures ") 
    output.write(str(numbers['passed_number']) + " Passed ")
    if numbers['ignored_number'] > 0 :
        output.write(str(numbers['ignored_number']) + " Ignored ")
    if numbers['assumption_failure'] > 0 :
        output.write(str(numbers['assumption_failure']) + " Assumption Failures ")
    output.write( str(numbers['total_number']) + " Total - " )
    output.write("Modules Run: " + str(numbers['modules_done']) + " Module Total: "+str(numbers['modules_total'])+"\n")
    output.write("    "+str(len(antiregressions)) + " Prior Failures now pass\n")
    for regression in regressions:
        # pdb.set_trace()
        if 'baseOS' in project_info: 
            OS = project_info['baseOS']
        else:
            OS = project_info['OS']
        testtype=classifyTest(flakes, regression['test_name'], project_info['hardware'], project_info['kern'], OS)
        # def classifyTest(flakeDicts, testcasename, hardware, kernel, android):
        #output.write("        " + testtype + " " + regression['test_name'] + "\n")
        output.write("        " + testtype + " " + regression['module_name'] +"." + regression['test_name'] + "\n")


def report_kernels_in_report(output, unique_kernels, unique_kernel_info): 
    output.write("\n")
    output.write("\n")
    output.write("Kernel/OS Combo(s) in this report:\n")
    for kernel in unique_kernels:
        output.write("    " + kernel+ " - ")
        combolist = unique_kernel_info[kernel]
        intercombo = iter(combolist)
        combo=combolist[0]
        output.write(combo)
        next(intercombo)
        for combo in intercombo:
            output.write(", "+ combo)
        output.write("\n")


class Command(BaseCommand):
    help = 'returns Android Common Kernel Regression Report for specific kernels'

    def add_arguments(self, parser):
        parser.add_argument('kernel', type=str, help='Kernel version')
        parser.add_argument('outputfile', type=str, help='Output File')
        parser.add_argument('flake', type=str, help='flakey file')
        parser.add_argument('exact', default='No', type=str, help='exact kernel version')

    def handle(self, *args, **options):
        kernel = options['kernel']
        scribblefile = options['outputfile'] + str(".scribble")
        output = open(scribblefile, "w")
        outputheader = open(options['outputfile'], "w")
        flakefile = open(options['flake'], "r")
        exact = options['exact']

        # map kernel to all available kernel, board, OS combos that match
        work = []
        unique_kernel_info = { }
        unique_kernels=[]

        work = rawkernels[kernel]
        flakes = process_flakey_file(flakefile)

        do_boilerplate(output)

        for combo in work:
            project_info = projectids[combo]
            project_id = project_info['project_id']
            project =  qa_report_api.get_project(project_id)
            builds = qa_report_api.get_all_builds(project_id)
            
            project_name = project.get('name')
            goodruns = find_best_two_runs(builds, project_name, project, exact)
            if len(goodruns) < 2 :
                print("\nERROR project " + project_name+ " did not have 2 good runs\n")
                output.write("\nERROR project " + project_name+ " did not have 2 good runs\n\n")
            else:
                add_unique_kernel(unique_kernels, goodruns[1]['version'], combo, unique_kernel_info)
                regressions = find_regressions(goodruns)
                antiregressions = find_antiregressions(goodruns)
                report_results(output, goodruns[1], regressions, combo, goodruns[0], flakes, antiregressions)
        report_kernels_in_report(outputheader, unique_kernels, unique_kernel_info)
        output.close()
        outputheader.close()
        
        bashCommand = "cat "+ str(scribblefile) +str(" >> ") + str(options['outputfile'])
        print(bashCommand)
        #process = subprocess.run(['cat', scribblefile, str('>>'+options['outputfile']) ], stdout=subprocess.PIPE)
        
"""
        except:
            raise CommandError('Kernel "%s" does not exist' % kernel)
"""
