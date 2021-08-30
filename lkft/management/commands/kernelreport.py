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
import logging
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
from lkft.views import get_build_metadata
from lkft.lkft_config import get_version_from_pname, get_kver_with_pname_env

logger = logging.getLogger(__name__)

qa_report_def = QA_REPORT[QA_REPORT_DEFAULT]
qa_report_api = qa_report.QAReportApi(qa_report_def.get('domain'), qa_report_def.get('token'))
jenkins_api = qa_report.JenkinsApi('ci.linaro.org', None)

rawkernels = {
    ## For gitlab pipeline tuxsuite builds
    'android-4.4-o-hikey': [
            '4.4o-8.1-hikey-tuxsuite',
            '4.4o-9.0-lcr-hikey-tuxsuite',
            '4.4o-10.0-gsi-hikey-tuxsuite',
            ],
    'android-4.4-p-hikey': [
            '4.4p-9.0-hikey-tuxsuite',
            '4.4p-10.0-gsi-hikey-tuxsuite',
            ],
    'android-4.9-o-hikey': [
            '4.9o-8.1-hikey-tuxsuite',
            '4.9o-9.0-lcr-hikey-tuxsuite',
            '4.9o-10.0-gsi-hikey-tuxsuite',
            '4.9o-10.0-gsi-hikey960-tuxsuite',
            ],
    'android-4.9-p-hikey': [
            "4.9p-9.0-hikey-tuxsuite",
            "4.9p-10.0-gsi-hikey-tuxsuite",
            "4.9p-9.0-hikey960-tuxsuite",
            "4.9p-10.0-gsi-hikey960-tuxsuite",
            ],
    'android-4.9-q-hikey': [
            "4.9q-10.0-gsi-hikey-tuxsuite",
            "4.9q-10.0-gsi-hikey960-tuxsuite",
            ],
    'android-4.14-p-hikey': [
            '4.14p-10.0-gsi-hikey960-tuxsuite',
            '4.14p-9.0-hikey960-tuxsuite',
            '4.14p-10.0-gsi-hikey-tuxsuite',
            '4.14p-9.0-hikey-tuxsuite',
            ],
    'android-4.14-q-hikey': [
            "4.14q-10.0-gsi-hikey-tuxsuite",
            "4.14q-10.0-gsi-hikey960-tuxsuite",
            ],
    'android-4.19-q-hikey': [
            '4.19q-10.0-gsi-hikey-tuxsuite',
            '4.19q-10.0-gsi-hikey960-tuxsuite',
            ],
    'android-mainline': [
            'android-mainlin-db845c-gitlab',
            'android-mainlin-hikey960-gitlab',
            'android-mainlin-x15-gitlab',
            'android-mainlin-hikey-gitlab',
            ],
    ########## for normal jenkins ci builds ##########
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
            '5.10-gki-android13-aosp-master-db845c',
            '5.10-gki-android13-aosp-master-hikey960',
            '5.10-gki-aosp-master-db845c',
            '5.10-gki-aosp-master-hikey960',
            ],
    'EAP510-lts':[
            '5.10-lts-gki-android12-private-android12-hikey960',
            '5.10-lts-gki-android12-private-android12-db845c',
            ],
    'EAP510':[
            '5.10-gki-private-android12-db845c',
            '5.10-gki-private-android12-hikey960',
            ],
    'EAP54':[
            '5.4-gki-private-android12-db845c',
            '5.4-gki-private-android12-hikey960',
            ],
    'mainline':[
            'mainline-gki-aosp-master-db845c',
            'mainline-gki-aosp-master-hikey960',
            'mainline-gki-aosp-master-hikey',
            'mainline-gki-aosp-master-x15',
            ],
}

projectids = {
    # for gitlab pipeline tuxsuite builds ###########

    ## for 4.4o
    '4.4o-8.1-hikey-tuxsuite': {
                                'slug': '4.4o-8.1-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'LCR-Android8',
                                'baseOS' : 'Android8',
                                'kern' : '4.4',
                                'branch' : 'Android-4.4-o',},
    '4.4o-9.0-lcr-hikey-tuxsuite': {
                                'slug': '4.4o-9.0-lcr-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'LCR-Android9',
                                'baseOS' : 'Android9',
                                'kern' : '4.4',
                                'branch' : 'Android-4.4-o',},
    '4.4o-10.0-gsi-hikey-tuxsuite': {
                                'slug': '4.4o-10.0-gsi-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'Android10',
                                'kern' : '4.4',
                                'branch' : 'Android-4.4-o',},
    ## for 4.4p
    '4.4p-9.0-hikey-tuxsuite': {
                                'slug': '4.4p-9.0-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'LCR-Android9',
                                'baseOS' : 'Android9',
                                'kern' : '4.4',
                                'branch' : 'Android-4.4-p',},
    '4.4p-10.0-gsi-hikey-tuxsuite': {
                                'slug': '4.4p-10.0-gsi-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'Android10',
                                'kern' : '4.4',
                                'branch' : 'Android-4.4-p',},

    ## for 4.9o
    '4.9o-8.1-hikey-tuxsuite': {
                        'slug': '4.9o-8.1-hikey',
                        'group':'~yongqin.liu',
                        'hardware': 'HiKey',
                        'OS' : 'Android10',
                        'kern' : '4.9',
                        'branch' : 'Android-4.9-o',},
    '4.9o-9.0-lcr-hikey-tuxsuite': {
                        'slug': '4.9o-9.0-lcr-hikey',
                        'group':'~yongqin.liu',
                        'hardware': 'HiKey',
                        'OS' : 'Android10',
                        'kern' : '4.9',
                        'branch' : 'Android-4.9-o',},
    '4.9o-10.0-gsi-hikey-tuxsuite': {
                        'slug': '4.9o-10.0-gsi-hikey',
                        'group':'~yongqin.liu',
                        'hardware': 'HiKey',
                        'OS' : 'Android10',
                        'kern' : '4.9',
                        'branch' : 'Android-4.9-o',},
    '4.9o-10.0-gsi-hikey960-tuxsuite': {
                        'slug': '4.9o-10.0-gsi-hikey960',
                        'group':'~yongqin.liu',
                        'hardware': 'HiKey960',
                        'OS' : 'Android10',
                        'kern' : '4.9',
                        'branch' : 'Android-4.9-o',},

    ## for 4.9p
    "4.9p-9.0-hikey-tuxsuite": {
                                'slug': '4.9p-9.0-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'Android10',
                                'kern' : '4.9',
                                'branch' : 'Android-4.9-p',},
    "4.9p-10.0-gsi-hikey-tuxsuite": {
                                'slug': '4.9p-10.0-gsi-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'Android10',
                                'kern' : '4.9',
                                'branch' : 'Android-4.9-p',},
    "4.9p-9.0-hikey960-tuxsuite": {
                                'slug': '4.9p-9.0-hikey960',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey960',
                                'OS' : 'Android10',
                                'kern' : '4.9',
                                'branch' : 'Android-4.9-p',},
    "4.9p-10.0-gsi-hikey960-tuxsuite": {
                                'slug': '4.9p-10.0-gsi-hikey960',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey960',
                                'OS' : 'Android10',
                                'kern' : '4.9',
                                'branch' : 'Android-4.9-p',},

    ## for 4.9q
    '4.9q-10.0-gsi-hikey-tuxsuite': {
                                'slug': '4.9q-10.0-gsi-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'Android10',
                                'kern' : '4.9',
                                'branch' : 'Android-4.9-q',},
    '4.9q-10.0-gsi-hikey960-tuxsuite': {
                                'slug': '4.9q-10.0-gsi-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey960',
                                'OS' : 'Android10',
                                'kern' : '4.9',
                                'branch' : 'Android-4.9-q',},

    ## for 4.14p
    '4.14p-9.0-hikey-tuxsuite': {
                                'slug': '4.14p-9.0-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'Android10',
                                'kern' : '4.14',
                                'branch' : 'Android-4.14-p',},
    '4.14p-10.0-gsi-hikey-tuxsuite': {
                                'slug': '4.14p-10.0-gsi-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'Android10',
                                'kern' : '4.14',
                                'branch' : 'Android-4.14-p',},
    '4.14p-9.0-hikey960-tuxsuite': {
                                'slug': '4.14p-9.0-hikey960',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey960',
                                'OS' : 'Android10',
                                'kern' : '4.14',
                                'branch' : 'Android-4.14-p',},
    '4.14p-10.0-gsi-hikey960-tuxsuite': {
                                'slug': '4.14p-10.0-gsi-hikey960',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey960',
                                'OS' : 'Android10',
                                'kern' : '4.14',
                                'branch' : 'Android-4.14-p',},

    ## for 4.14q
    '4.14q-10.0-gsi-hikey-tuxsuite': {
                                'slug': '4.14q-10.0-gsi-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'Android10',
                                'kern' : '4.14',
                                'branch' : 'Android-4.14-q',},
    '4.14q-10.0-gsi-hikey960-tuxsuite': {
                                'slug': '4.14q-10.0-gsi-hikey960',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey960',
                                'OS' : 'Android10',
                                'kern' : '4.14',
                                'branch' : 'Android-4.14-q',},

    ## for 4.19q
    '4.19q-10.0-gsi-hikey-tuxsuite': {
                                'slug': '4.19q-10.0-gsi-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'Android10',
                                'kern' : '4.19',
                                'branch' : 'Android-4.19-q',},
    '4.19q-10.0-gsi-hikey960-tuxsuite': {
                                'slug': '4.19q-10.0-gsi-hikey960',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey960',
                                'OS' : 'Android10',
                                'kern' : '4.19',
                                'branch' : 'Android-4.19-q',},

    ## for mainline
    'android-mainlin-x15-gitlab': {
                                'slug': 'mainline-aosp-master-x15',
                                'group':'~yongqin.liu',
                                'hardware': 'X15',
                                'OS' : 'AOSP',
                                'kern' : '5.X',
                                'branch' : 'android-mainline',},
    'android-mainlin-hikey-gitlab': {
                                'slug': 'mainline-gki-aosp-master-hikey',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey',
                                'OS' : 'AOSP',
                                'kern' : '5.X',
                                'branch' : 'android-mainline',},
    'android-mainlin-hikey960-gitlab': {
                                'slug': 'mainline-gki-aosp-master-hikey960',
                                'group':'~yongqin.liu',
                                'hardware': 'HiKey960',
                                'OS' : 'AOSP',
                                'kern' : '5.X',
                                'branch' : 'android-mainline',},
    'android-mainlin-db845c-gitlab': {
                                'slug': 'mainline-gki-aosp-master-db845c',
                                'group':'~yongqin.liu',
                                'hardware': 'db845',
                                'OS' : 'AOSP',
                                'kern' : '5.X',
                                'branch' : 'android-mainline',},

    ########## for jenkins ci builds ###################
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
                     'branch' : 'Android12-5.10',},
    '5.10-gki-aosp-master-db845c':
                    {'project_id': 606,
                     'hardware': 'db845',
                     'OS' : 'AOSP',
                     'kern' : '5.10',
                     'branch' : 'Android12-5.10',},
    '5.10-gki-android13-aosp-master-hikey960':
                    {'project_id': 731,
                     'hardware': 'HiKey960',
                     'OS' : 'AOSP',
                     'kern' : '5.10',
                     'branch' : 'Android13-5.10',},
    '5.10-gki-android13-aosp-master-db845c':
                    {'project_id': 730,
                     'hardware': 'db845',
                     'OS' : 'AOSP',
                     'kern' : '5.10',
                     'branch' : 'Android13-5.10',},
    '5.10-gki-private-android12-db845c':
                    {'project_id': 617,
                     'hardware': 'db845',
                     'OS' : 'Android12',
                     'kern' : '5.10',
                     'branch' : 'Android12-5.10',},
    '5.10-gki-private-android12-hikey960':
                    {'project_id': 616,
                     'hardware': 'HiKey960',
                     'OS' : 'Android12',
                     'kern' : '5.10',
                     'branch' : 'Android-5.10',},

    '5.10-lts-gki-android12-private-android12-hikey960':
                    {'slug': '5.10-lts-gki-android12-private-android12-hikey960',
                     'group': 'android-lkft',
                     'hardware': 'HiKey960',
                     'OS' : 'Android12',
                     'kern' : '5.10',
                     'branch' : 'Android-5.10-lts',},
    '5.10-lts-gki-android12-private-android12-db845c':
                    {'slug': '5.10-lts-gki-android12-private-android12-db845c',
                     'group': 'android-lkft',
                     'hardware': 'db845',
                     'OS' : 'Android12',
                     'kern' : '5.10',
                     'branch' : 'Android-5.10-lts',},
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

    'mainline-gki-aosp-master-db845c':
                    {'project_id': 236,
                     'hardware': 'db845',
                     'OS' : 'AOSP',
                     'kern' : 'android-mainline',
                     'branch' : 'android-mainline',},
    'mainline-gki-aosp-master-hikey960':
                    {'project_id': 219,
                     'hardware': 'HiKey960',
                     'OS' : 'AOSP',
                     'kern' : 'android-mainline',
                     'branch' : 'android-mainline',},
    'mainline-gki-aosp-master-hikey':
                    {'project_id': 216,
                     'hardware': 'Hikey',
                     'OS' : 'AOSP',
                     'kern' : 'android-mainline',
                     'branch' : 'android-mainline',},
    'mainline-gki-aosp-master-x15':
                    {'project_id': 237,
                     'hardware': 'x15',
                     'OS' : 'AOSP',
                     'kern' : 'android-mainline',
                     'branch' : 'android-mainline',},

}

def do_boilerplate(output):
    output.write("\n\nFailure Key:\n")
    output.write("--------------------\n")
    output.write("I == Investigation\nB == Bug#, link to bugzilla\nF == Flakey\nU == Unexpected Pass\n\n")

# a flake entry
# name, state, bugzilla
def process_flakey_file(path_flakefile):
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

    f_flakefile = open(path_flakefile, "r")
    Lines = f_flakefile.readlines()
    f_flakefile.close()
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
               testentry['androidrel'].append('Android8') #O
               testentry['androidrel'].append('Android9') #P
               testentry['androidrel'].append('Android10') #Q
               testentry['androidrel'].append('Android11') #R
               testentry['androidrel'].append('Android12') #S
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
    ## 5.13.0, 5.13.0-50292ffdbbdb, 5.14.0-rc2, or 5.14.0-rc2-754a0abed174
    versionDict = { 'Major':0,
                    'Minor':0,
                    'Extra':0,
                    'versionString': versionString}

    if versionString.startswith('v'):
        versionString = versionString[1:]
    # print versionString
    tokens = re.split( r'[.-]', versionString)
    # print tokens
    if tokens[0].isnumeric() and tokens[1].isnumeric() and tokens[2].isnumeric():
        versionDict['Major'] = tokens[0]
        versionDict['Minor'] = tokens[1]
        versionDict['Extra'] = tokens[2]

    tokens_hyphen = versionString.split('-')
    if len(tokens_hyphen) >= 2:
        if tokens_hyphen[1].startswith('rc'):
            # for case of 5.14.0-rc2, or 5.14.0-rc2-754a0abed174
            versionDict['rc'] = tokens_hyphen[1]
            if len(tokens_hyphen) == 3:
                versionDict['sha'] = tokens_hyphen[2]
            else:
                # for case of 5.14.0-rc2, no sha specified
                pass
        else:
            # for case of 5.13.0-50292ffdbbdb, not rc version
            versionDict['sha'] = tokens_hyphen[1]
    else:
        # for case of 5.13.0, not rc version, and no sha specified
        pass

    return versionDict


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


def find_best_two_runs(builds, project_name, project, exact_ver1="", exact_ver2="", reverse_build_order=False, no_check_kernel_version=False):
    goodruns = []
    bailaftertwo = 0
    number_of_build_with_jobs = 0
    baseExactVersionDict=None
    nextVersionDict=None

    if len(exact_ver1) > 0 and exact_ver1 !='No':
        baseExactVersionDict = versiontoMME(exact_ver1)

    for build in builds:
        if bailaftertwo == 2:
            break
        elif bailaftertwo == 0 :
            baseVersionDict = versiontoMME(build['version'])
            if baseExactVersionDict is not None \
                    and not baseVersionDict['versionString'].startswith(exact_ver1):
                logger.info('Skip the check as it is not the specified version for %s %s', project_name, build['version'])
                continue
            # print "baseset"
        elif bailaftertwo == 1 :
            nextVersionDict = versiontoMME(build['version'])
            if exact_ver2 is not None \
                    and not nextVersionDict['versionString'].startswith(exact_ver2):
                # for case that second build version specified, but not this build
                logger.info('Skip the check as it is not the specified version for %s %s', project_name, build['version'])
                continue
            elif not no_check_kernel_version and nextVersionDict['Extra'] == baseVersionDict['Extra']:
                # for case that need to check kernel version, and all major, minro, extra version are the same
                # then needs to check if the rc version is the same too
                nextRc = nextVersionDict.get('rc')
                baseRc = baseVersionDict.get('rc')
                if (nextRc is None and baseRc is None) \
                    or (nextRc is not None and baseRc is not None and nextRc == baseRc):
                    # for case that neither build is rc version or both have the same rc version
                    logger.info('Skip the check as it has the same version for %s %s', project_name, build['version'])
                    continue
                else:
                    # for case that the rc version are different, like
                    # 1. one build is rc version, but another is not rc version
                    # 2. both are rc versions, but are different rc versions
                    pass
            else:
                # for cases that
                # 1. the second build version not specified, or this build has the same version like the specified second build version
                # 2. no need to check the kernel version, or the kernel version is different, either extra version or the rc version
                pass

        logger.info("Checking for %s, %s", project_name, build.get('version'))
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

            tallyNumbers(build, jobTransactionStatus)

            if nextVersionDict is not None:
                # add for the second build
                if exact_ver2 is not None:
                    if reverse_build_order:
                        # find regression in exact_ver2 compare to exact_ver1
                        goodruns.append(build)
                    else:
                        # find regression in exact_ver1 compare to exact_ver2
                        goodruns.insert(0, build)

                elif int(nextVersionDict['Extra']) > int(baseVersionDict['Extra']):
                    # for the case the second build is newer than the first build
                    # first build is goodruns[0], second build is goodruns[1]
                    # normally, the builds are sorted with the newest kernel version as the first build.
                    goodruns.append(build)
                else:
                    # for the case the second build is older than or equal to the first build
                    goodruns.insert(0, build)
            else:
                # add for the first build
                goodruns.append(build)

            bailaftertwo += 1
        elif bailaftertwo == 0 and exact_ver1 is not None and baseVersionDict is not None and baseVersionDict.get('versionString') == exact_ver1:
            # found the first build with exact_ver1, but that build does not have all jobs finished successfully
            # stop the loop for builds to find anymore
            bailaftertwo += 1
            return goodruns
        elif bailaftertwo == 1 and exact_ver2 is not None and nextVersionDict is not None and nextVersionDict.get('versionString') == exact_ver2:
            # found the second build with exact_ver2, but that build does not have all jobs finished successfully
            # stop the loop for builds to find anymore
            bailaftertwo += 1
            return goodruns
        else:
            # for case that no completed build found, continute to check the next build
            continue

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

# Try to find the regressions in goodruns[1]
# compared to the result in goodruns[0]
def find_regressions(goodruns):
    runA = goodruns[1]
    failuresA = runA['failures_list']
    runB = goodruns[0]
    failuresB = runB['failures_list']
    regressions = []
    for failureA in failuresA:
        match = 0
        testAname = failureA['test_name']
        for failureB in failuresB:
            testBname = failureB['test_name']
            if testAname == testBname:
                match = 1
                break
        if match != 1 :
            # for failures in goodruns[1],
            # if they are not reported in goodruns[0],
            # then they are regressions
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

def print_androidresultheader(output, project_info, run, priorrun):
    output.write("    " + project_info['OS'] + "/" + project_info['hardware'] + " - " )
    output.write("Current:" + run['version'] + "  Prior:" + priorrun['version']+"\n")

    build_metadata = get_build_metadata(build_metadata_url=run.get('metadata'))
    prior_build_metadata = get_build_metadata(build_metadata_url=priorrun.get('metadata'))


    def get_last_of_metadata(metadata):
        if metadata is None:
            return None
        if type(metadata) is str:
            return metadata
        if type(metadata) is list:
            return metadata[-1]

    if build_metadata.get('gsi_fingerprint', None):
        output.write("    " + "GSI Fingerprint:" + " - " )
        if get_last_of_metadata(build_metadata.get('gsi_fingerprint')) == get_last_of_metadata(prior_build_metadata.get('gsi_fingerprint', 'UNKNOWN')):
            output.write("Current:" + get_last_of_metadata(build_metadata.get('gsi_fingerprint')) + " == Prior:" + get_last_of_metadata(prior_build_metadata.get('gsi_fingerprint', 'UNKNOWN')) + "\n")
        else:
            output.write("Current:" + get_last_of_metadata(build_metadata.get('gsi_fingerprint')) + " != Prior:" + get_last_of_metadata(prior_build_metadata.get('gsi_fingerprint', 'UNKNOWN')) + "\n")

    if build_metadata.get('vendor_fingerprint', None):
        output.write("    " + "Vendor Fingerprint:" + " - " )
        if get_last_of_metadata(build_metadata.get('vendor_fingerprint')) == get_last_of_metadata(prior_build_metadata.get('vendor_fingerprint', 'UNKNOWN')):
            output.write("Current:" + get_last_of_metadata(build_metadata.get('vendor_fingerprint')) + " == Prior:" + get_last_of_metadata(prior_build_metadata.get('vendor_fingerprint', 'UNKNOWN')) + "\n")
        else:
            output.write("Current:" + get_last_of_metadata(build_metadata.get('vendor_fingerprint')) + " != Prior:" + get_last_of_metadata(prior_build_metadata.get('vendor_fingerprint', 'UNKNOWN')) + "\n")

    output.write("    " + "CTS Version:" + " - " )
    if get_last_of_metadata(build_metadata.get('cts_version', 'UNKNOWN')) == get_last_of_metadata(prior_build_metadata.get('cts_version', 'UNKNOWN')):
        output.write("Current:" + get_last_of_metadata(build_metadata.get('cts_version', 'UNKNOWN')) + " == Prior:" + get_last_of_metadata(prior_build_metadata.get('cts_version', 'UNKNOWN')) + "\n")
    else:
        output.write("Current:" + get_last_of_metadata(build_metadata.get('cts_version', 'UNKNOWN')) + " != Prior:" + get_last_of_metadata(prior_build_metadata.get('cts_version', 'UNKNOWN')) + "\n")

    output.write("    " + "VTS Version:" + " - " )
    if get_last_of_metadata(build_metadata.get('vts_version', 'UNKNOWN')) == get_last_of_metadata(prior_build_metadata.get('vts_version', 'UNKNOWN')):
        output.write("Current:" + get_last_of_metadata(build_metadata.get('vts_version', 'UNKNOWN')) + " == Prior:" + get_last_of_metadata(prior_build_metadata.get('vts_version', 'UNKNOWN')) + "\n")
    else:
        output.write("Current:" + get_last_of_metadata(build_metadata.get('vts_version', 'UNKNOWN')) + " != Prior:" + get_last_of_metadata(prior_build_metadata.get('vts_version', 'UNKNOWN')) + "\n")


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


def report_kernels_in_report(path_outputfile, unique_kernels, unique_kernel_info):
    with open(path_outputfile, "w") as f_outputfile:
        f_outputfile.write("\n")
        f_outputfile.write("\n")
        f_outputfile.write("Kernel/OS Combo(s) in this report:\n")
        for kernel in unique_kernels:
            f_outputfile.write("    " + kernel+ " - ")
            combolist = unique_kernel_info[kernel]
            intercombo = iter(combolist)
            combo=combolist[0]
            f_outputfile.write(combo)
            next(intercombo)
            for combo in intercombo:
                f_outputfile.write(", "+ combo)
            f_outputfile.write("\n")


class Command(BaseCommand):
    help = 'returns Android Common Kernel Regression Report for specific kernels'

    def add_arguments(self, parser):
        parser.add_argument('kernel', type=str, help='Kernel version')
        parser.add_argument('outputfile', type=str, help='Output File')
        parser.add_argument('flake', type=str, help='flakey file')
        parser.add_argument("--no-check-kernel-version",
                help="Specify if the kernel version for the build should be checked.",
                dest="no_check_kernel_version",
                action='store_true',
                required=False)

        parser.add_argument("--exact-version-1",
                help="Specify the exact kernel version for the first build",
                dest="exact_version_1",
                default="",
                required=False)
        parser.add_argument("--exact-version-2",
                help="Specify the exact kernel version for the second build",
                dest="exact_version_2",
                default="",
                required=False)
        parser.add_argument("--reverse-build-order",
                help="When both --exact-version-1 and --exact-version-2 specified,\
                 normally will try to find the regressions in --exact-version-1 against --exact-version-2,\
                 but with this option, it will try to find the regressions in --exact-version-2\
                 agains the build of --exact-version-1",
                dest="reverse_build_order",
                action='store_true',
                required=False)


    def handle(self, *args, **options):
        kernel = options['kernel']
        path_outputfile = options['outputfile']
        scribblefile = path_outputfile + str(".scribble")
        path_flakefile = options['flake']

        no_check_kernel_version = options.get('no_check_kernel_version')
        opt_exact_ver1 = options.get('exact_version_1')
        opt_exact_ver2 = options.get('exact_version_2')
        reverse_build_order = options.get('reverse_build_order')

        # map kernel to all available kernel, board, OS combos that match
        work = []
        unique_kernel_info = { }
        unique_kernels=[]

        work = rawkernels.get(kernel)
        if work is None:
            print("The specified kernel is not supported yet:", kernel)
            print("The supported kernels are:", ' '.join(rawkernels.keys()))
            return

        flakes = process_flakey_file(path_flakefile)

        output = open(scribblefile, "w")
        do_boilerplate(output)

        for combo in work:
            project_info = projectids[combo]
            project_id = project_info.get('project_id', None)
            if project_id is not None:
                logger.info("Try to get project %s with project_id %s", combo, project_id)
                project =  qa_report_api.get_project(project_id)
            else:
                project_group = project_info.get('group', None)
                project_slug = project_info.get('slug', None)
                project_fullname = qa_report_api.get_project_full_name_with_group_and_slug(project_group, project_slug)

                logger.info("Try to get project %s with project_fullname %s", combo, project_fullname)
                project =  qa_report_api.get_project_with_name(project_fullname)

            if project is None:
                print("\nERROR project for " + combo + " was not found, please check and try again\n")
                output.write("\nERROR project for " + combo+ " was not found, please check and try again\n\n")
                continue

            project_id = project.get('id')
            builds = qa_report_api.get_all_builds(project_id)
            
            project_name = project.get('name')
            goodruns = find_best_two_runs(builds, project_name, project,
                                          exact_ver1=opt_exact_ver1, exact_ver2=opt_exact_ver2, reverse_build_order=reverse_build_order,
                                          no_check_kernel_version=no_check_kernel_version)
            if len(goodruns) < 2 :
                print("\nERROR project " + project_name+ " did not have 2 good runs\n")
                output.write("\nERROR project " + project_name+ " did not have 2 good runs\n\n")
            else:
                add_unique_kernel(unique_kernels, goodruns[1]['version'], combo, unique_kernel_info)
                regressions = find_regressions(goodruns)
                antiregressions = find_antiregressions(goodruns)
                report_results(output, goodruns[1], regressions, combo, goodruns[0], flakes, antiregressions)

        report_kernels_in_report(path_outputfile, unique_kernels, unique_kernel_info)
        output.close()
        
        bashCommand = "cat "+ str(scribblefile) +str(" >> ") + path_outputfile
        print(bashCommand)
        #process = subprocess.run(['cat', scribblefile, str('>>'+options['outputfile']) ], stdout=subprocess.PIPE)
        
"""
        except:
            raise CommandError('Kernel "%s" does not exist' % kernel)
"""
