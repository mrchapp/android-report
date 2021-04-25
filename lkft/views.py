# -*- coding: utf-8 -*-
from __future__ import unicode_literals


from django import forms
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render, redirect

import collections
import concurrent.futures
import datetime
import functools
import json
import logging
import math
import os
import re
import requests
import sys
import tarfile
import threading
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User, AnonymousUser, Group as auth_group
from django.utils.timesince import timesince

from lcr.settings import FILES_DIR, LAVA_SERVERS, BUGZILLA_API_KEY, BUILD_WITH_JOBS_NUMBER
from lcr.settings import QA_REPORT, QA_REPORT_DEFAULT, JENKINS, JENKINS_DEFAULT
from lcr.settings import RESTRICTED_PROJECTS
from lcr.irc import IRC

from lcr import qa_report, bugzilla
from lcr.qa_report import DotDict, UrlNotFoundException
from lcr.utils import download_urllib
from lkft.lkft_config import find_citrigger, find_cibuild, get_hardware_from_pname, get_version_from_pname, get_kver_with_pname_env
from lkft.lkft_config import find_expect_cibuilds
from lkft.lkft_config import get_qa_server_project, get_supported_branches
from lkft.lkft_config import is_benchmark_job, is_cts_vts_job, get_benchmark_testsuites, get_expected_benchmarks

from .models import KernelChange, CiBuild, ReportBuild, ReportProject, ReportJob, TestCase

qa_report_def = QA_REPORT[QA_REPORT_DEFAULT]
qa_report_api = qa_report.QAReportApi(qa_report_def.get('domain'), qa_report_def.get('token'))
jenkins_def = JENKINS[JENKINS_DEFAULT]
jenkins_api = qa_report.JenkinsApi(jenkins_def.get('domain'), jenkins_def.get('token'), user=jenkins_def.get('user'))
irc = IRC.getInstance()

DIR_ATTACHMENTS = os.path.join(FILES_DIR, 'lkft')
logger = logging.getLogger(__name__)

TEST_RESULT_XML_NAME = 'test_result.xml'

class LinaroAndroidLKFTBug(bugzilla.Bugzilla):

    def __init__(self, host_name, api_key):
        self.host_name = host_name
        self.new_bug_url_prefix = "https://%s/enter_bug.cgi" % self.host_name
        self.rest_api_url = "https://%s/rest" % self.host_name
        self.show_bug_prefix = 'https://%s/show_bug.cgi?id=' % self.host_name

        self.product = 'Linaro Android'
        self.component = 'General'
        self.bug_severity = 'normal'
        self.op_sys = 'Android'
        self.keywords = "LKFT"

        super(LinaroAndroidLKFTBug, self).__init__(self.rest_api_url, api_key)

        #self.build_version = None
        #self.hardware = None
        #self.version = None

    def get_new_bug_url_prefix(self):
        new_bug_url = '%s?product=%s&op_sys=%s&bug_severity=%s&component=%s&keywords=%s' % ( self.new_bug_url_prefix,
                                                                                                   self.product,
                                                                                                   self.op_sys,
                                                                                                   self.bug_severity,
                                                                                                   self.component,
                                                                                                   self.keywords)
        return new_bug_url

bugzilla_host_name = 'bugs.linaro.org'
bugzilla_instance = LinaroAndroidLKFTBug(host_name=bugzilla_host_name, api_key=BUGZILLA_API_KEY)
bugzilla_show_bug_prefix = bugzilla_instance.show_bug_prefix

def find_lava_config(job_url):
    if job_url is None:
        return None
    for nick, config in LAVA_SERVERS.items():
        if job_url.find('://%s/' % config.get('hostname')) >= 0:
            return config
    return None

def get_attachment_urls(jobs=[]):
    '''
        ALL JOBS must be belong to the same build
    '''
    if len(jobs) == 0:
        return

    needs_attachment_urls = False
    for job in jobs:
        lava_config = job.get('lava_config')
        if not lava_config :
            lava_config = find_lava_config(job.get('external_url'))
            if lava_config:
                job['lava_config'] = lava_config
            else:
                logger.error('lava server is not found for job: %s' % job.get('url'))

        if is_benchmark_job(job.get('name')):
            continue

        if job.get("attachment_url") is not None:
            continue

        if not is_cts_vts_job(job.get('name')):
            continue

        try:
            db_report_job = ReportJob.objects.get(job_url=job.get('external_url'))
            if not job.get('job_status') or job.get('job_status') == 'Submitted' or job.get('job_status') == 'Running' \
                    or not db_report_job.status or db_report_job.status != 'Complete' or db_report_job.status != 'Incomplete' or db_report_job.status != 'Canceled':
                needs_attachment_urls = True
                continue
            else: # Complete
                job["attachment_url"] = db_report_job.attachment_url
        except ReportJob.DoesNotExist:
            needs_attachment_urls = True
            pass

    if not needs_attachment_urls:
        return

    first_job = jobs[0]
    target_build_id = first_job.get('target_build').strip('/').split('/')[-1]
    db_report_build = get_build_from_database_or_qareport(target_build_id)[1]
    target_build_metadata = qa_report_api.get_build_meta_with_url(db_report_build.metadata_url)

    for job in jobs:
        if not job.get('job_status') or job.get('job_status') == 'Submitted' \
                or job.get('job_status') == 'Running' \
                or job.get('job_status') == 'Canceled' :
            # the job is still in queue, so it should not have attachment yet
            continue

        attachment_url_key = 'tradefed_results_url_%s' % job.get('job_id')
        attachment_url = target_build_metadata.get(attachment_url_key)
        if attachment_url is not None:
            job['attachment_url'] = attachment_url
        elif is_benchmark_job(job.get('name')):
            #get_benchmark_testsuites
            pass
        else:
            pass


def extract_save_result(tar_path, result_zip_path):
    zip_parent = os.path.abspath(os.path.join(result_zip_path, os.pardir))
    if not os.path.exists(zip_parent):
        os.makedirs(zip_parent)
    # https://pymotw.com/2/zipfile/
    tar = tarfile.open(tar_path, "r")
    for f_name in tar.getnames():
        if f_name.endswith("/%s" % TEST_RESULT_XML_NAME):
            result_fd = tar.extractfile(f_name)
            with zipfile.ZipFile(result_zip_path, 'w') as f_zip_fd:
                f_zip_fd.writestr(TEST_RESULT_XML_NAME, result_fd.read(), compress_type=zipfile.ZIP_DEFLATED)
                logger.info('Save result in %s to %s' % (tar_path, result_zip_path))

    tar.close()


def get_result_file_path(job=None):
    if not job.get('lava_config'):
        return None
    lava_nick = job.get('lava_config').get('nick')
    job_id = job.get('job_id')
    result_file_path = os.path.join(DIR_ATTACHMENTS, "%s-%s.zip" % (lava_nick, job_id))
    return result_file_path


def download_attachments_save_result(jobs=[]):
    if len(jobs) == 0:
        return

    # https://lkft.validation.linaro.org/scheduler/job/566144
    get_attachment_urls(jobs=jobs)
    for job in jobs:
        # cache all the jobs, otherwise the status is not correct for the build
        # if incomplete jobs are not cached.
        report_job = cache_qajob_to_database(job)
        if report_job.results_cached:
            continue

        if not job.get('lava_config'):
            continue

        if job.get('job_status') != 'Complete':
            continue

        if is_benchmark_job(job.get('name')):
            # for benchmark jobs
            lava_config = job.get('lava_config')
            job_id = job.get('job_id')
            job_results = qa_report.LAVAApi(lava_config=lava_config).get_job_results(job_id=job_id)
            for test in job_results:
                if test.get("suite") == "lava":
                    continue
                # if pat_ignore.match(test.get("name")):
                #     continue

                # if test.get("name") in names_ignore:
                #     continue
                if test.get("measurement") and test.get("measurement") == "None":
                    test["measurement"] = None
                else:
                    test["measurement"] = "{:.2f}".format(float(test.get("measurement")))
                need_cache = False
                try:
                    # not set again if already cached
                    TestCase.objects.get(name=test.get("name"),
                                         suite=test.get("suite"),
                                         lava_nick=lava_config.get('nick'),
                                         job_id=job_id)
                except TestCase.DoesNotExist:
                    need_cache = True
                except TestCase.MultipleObjectsReturned:
                    TestCase.objects.filter(name=test.get("name"),
                                            suite=test.get("suite"),
                                            lava_nick=lava_config.get('nick'),
                                            job_id=job_id).delete()
                    need_cache = True

                if need_cache:
                    TestCase.objects.create(name=test.get("name"),
                                            result=test.get("result"),
                                            measurement=test.get("measurement"),
                                            unit=test.get("unit"),
                                            suite=test.get("suite"),
                                            lava_nick=lava_config.get('nick'),
                                            job_id=job_id)


        elif is_cts_vts_job(job.get('name')):
            # for cts /vts jobs
            job_id = job.get('job_id')
            job_url = job.get('external_url')
            result_file_path = get_result_file_path(job)
            if not result_file_path:
                logger.info("Skip to get the attachment as the result_file_path is not found: %s %s" % (job_url, job.get('url')))
                continue
            if not os.path.exists(result_file_path):
                if job.get('job_status') != 'Complete':
                    logger.info("Skip to get the attachment as the job is not Complete: %s %s" % (job_url, job.get('name')))
                    continue

                attachment_url = job.get('attachment_url')
                if not attachment_url:
                    logger.info("No attachment for job: %s %s" % (job_url, job.get('name')))
                    continue

                (temp_fd, temp_path) = tempfile.mkstemp(suffix='.tar.xz', text=False)
                logger.info("Start downloading result file for job %s %s: %s" % (job_url, job.get('name'), temp_path))
                ret_err = download_urllib(attachment_url, temp_path)
                if ret_err:
                    logger.info("There is a problem with the size of the file: %s" % attachment_url)
                    continue
                else:
                    tar_f = temp_path.replace(".xz", '')
                    ret = os.system("xz -d %s" % temp_path)
                    if ret == 0 :
                        extract_save_result(tar_f, result_file_path)
                        os.unlink(tar_f)
                    else:
                        logger.info("Failed to decompress %s with xz -d command for job: %s " % (temp_path, job_url))

            job_numbers = get_testcases_number_for_job(job)
            qa_report.TestNumbers.setHashValueForDatabaseRecord(report_job, job_numbers)
        else:
            # for other jobs like the boot job and other benchmark jobs
            pass

        report_job.results_cached = True
        report_job.finished_successfully = True
        report_job.save()


def remove_xml_unsupport_character(etree_content=""):
    rx = re.compile("&#([0-9]+);|&#x([0-9a-fA-F]+);")
    endpos = len(etree_content)
    pos = 0
    while pos < endpos:
        # remove characters that don't conform to XML spec
        m = rx.search(etree_content, pos)
        if not m:
            break
        mstart, mend = m.span()
        target = m.group(1)
        if target:
            num = int(target)
        else:
            num = int(m.group(2), 16)
        # #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
        if not(num in (0x9, 0xA, 0xD)
                or 0x20 <= num <= 0xD7FF
                or 0xE000 <= num <= 0xFFFD
                or 0x10000 <= num <= 0x10FFFF):
            etree_content = etree_content[:mstart] + etree_content[mend:]
            endpos = len(etree_content)
            # next time search again from the same position as this time
            # as the detected pattern was removed here
            pos = mstart
        else:
            # continue from the end of this match
            pos = mend
    return etree_content


def extract(result_zip_path, failed_testcases_all={}, metadata={}):
    kernel_version = metadata.get('kernel_version')
    platform = metadata.get('platform')
    qa_job_id = metadata.get('qa_job_id')
    number_total = 0
    number_passed = 0
    number_failed = 0
    number_assumption_failure = 0
    number_ignored = 0
    modules_done = 0
    modules_total = 0

    # no affect for cts result and non vts-hal test result
    vts_abi_suffix_pat = re.compile(r"_32bit$|_64bit$")
    with zipfile.ZipFile(result_zip_path, 'r') as f_zip_fd:
        try:
            # https://docs.python.org/3/library/xml.etree.elementtree.html
            root = ET.fromstring(remove_xml_unsupport_character(f_zip_fd.read(TEST_RESULT_XML_NAME).decode('utf-8')))
            summary_node = root.find('Summary')
            number_passed = int(summary_node.attrib['pass'])
            number_failed = int(summary_node.attrib['failed'])
            assumption_failures = root.findall(".//Module/TestCase/Test[@result='ASSUMPTION_FAILURE']")
            number_assumption_failure = len(assumption_failures)
            ignored_testcases = root.findall(".//Module/TestCase/Test[@result='IGNORED']")
            number_ignored = len(ignored_testcases)
            all_testcases = root.findall(".//Module/TestCase/Test")
            number_total = len(all_testcases)
            modules_done = int(summary_node.attrib['modules_done'])
            modules_total = int(summary_node.attrib['modules_total'])

            for elem in root.findall('Module'):
                abi = elem.attrib['abi']
                module_name = elem.attrib['name']

                failed_tests_module = failed_testcases_all.get(module_name)
                if not failed_tests_module:
                    failed_tests_module = {}
                    failed_testcases_all[module_name] = failed_tests_module

                # test classes
                test_cases = elem.findall('.//TestCase')
                for test_case in test_cases:
                    failed_tests = test_case.findall('.//Test[@result="fail"]')
                    assumption_failures = test_case.findall('.//Test[@result="ASSUMPTION_FAILURE"]')
                    for failed_test in failed_tests + assumption_failures:
                        #test_name = '%s#%s' % (test_case.get("name"), vts_abi_suffix_pat.sub('', failed_test.get("name")))
                        mod_name = test_case.get("name")
                        test_result = failed_test.get('result')
                        test_name = failed_test.get("name")
                        if test_name.endswith('_64bit') or test_name.endswith('_32bit'):
                            test_name = '%s#%s' % (mod_name, test_name)
                        else: 
                            test_name = '%s#%s#%s' % (mod_name, test_name, abi)
                        message = failed_test.find('.//Failure').attrib.get('message')
                        stacktrace = failed_test.find('.//Failure/StackTrace').text
                        ## ignore duplicate cases as the jobs are for different modules
                        failed_testcase = failed_tests_module.get(test_name)
                        if failed_testcase:
                            if failed_testcase.get('abi_stacktrace').get(abi) is None:
                                failed_testcase.get('abi_stacktrace')[abi] = stacktrace

                            if not qa_job_id in failed_testcase.get('qa_job_ids'):
                                failed_testcase.get('qa_job_ids').append(qa_job_id)

                            if not kernel_version in failed_testcase.get('kernel_versions'):
                                failed_testcase.get('kernel_versions').append(kernel_version)

                            if not platform in failed_testcase.get('platforms'):
                                failed_testcase.get('platforms').append(platform)
                        else:
                            failed_tests_module[test_name]= {
                                                                'test_name': test_name,
                                                                'module_name': module_name,
                                                                'result': test_result,
                                                                'test_class': test_case.get("name"),
                                                                'test_method': failed_test.get("name"),
                                                                'abi_stacktrace': {abi: stacktrace},
                                                                'message': message,
                                                                'qa_job_ids': [ qa_job_id ],
                                                                'kernel_versions': [ kernel_version ],
                                                                'platforms': [ platform ],
                                                            }

        except ET.ParseError as e:
            logger.error('xml.etree.ElementTree.ParseError: %s' % e)
            logger.info('Please Check %s manually' % result_zip_path)

    numbers_hash = {
                'number_total': number_total,
                'number_passed': number_passed,
                'number_failed': number_failed,
                'number_assumption_failure': number_assumption_failure,
                'number_ignored': number_ignored,
                'modules_done': modules_done,
                'modules_total': modules_total,
            }
    test_numbers = qa_report.TestNumbers()
    test_numbers.addWithHash(numbers_hash)
    return test_numbers


def get_last_trigger_build(project=None):
    ci_trigger_name = find_citrigger(project=project)
    if not ci_trigger_name:
        return None
    return jenkins_api.get_last_build(cijob_name=ci_trigger_name)


def get_testcases_number_for_job(job):
    job_number_passed = 0
    job_number_failed = 0
    job_number_assumption_failure = 0
    job_number_ignored = 0
    job_number_total = 0
    modules_total = 0
    modules_done = 0
    finished_successfully = False

    job_name = job.get('name')
    #'benchmark', 'boottime', '-boot', '-vts', 'cts', 'cts-presubmit'
    is_cts_vts_job = job_name.find('cts') >= 0 or job_name.find('vts') >= 0
    if is_cts_vts_job:
        result_file_path = get_result_file_path(job=job)
        if result_file_path and os.path.exists(result_file_path):
            try:
                with zipfile.ZipFile(result_file_path, 'r') as f_zip_fd:
                    try:
                        root = ET.fromstring(remove_xml_unsupport_character(f_zip_fd.read(TEST_RESULT_XML_NAME).decode('utf-8')))
                        summary_node = root.find('Summary')
                        job_number_passed = summary_node.attrib['pass']
                        job_number_failed = summary_node.attrib['failed']
                        assumption_failures = root.findall(".//Module/TestCase/Test[@result='ASSUMPTION_FAILURE']")
                        job_number_assumption_failure = len(assumption_failures)
                        ignored_testcases = root.findall(".//Module/TestCase/Test[@result='IGNORED']")
                        job_number_ignored = len(ignored_testcases)
                        all_testcases = root.findall(".//Module/TestCase/Test")
                        job_number_total = len(all_testcases)
                        modules_total = summary_node.attrib['modules_total']
                        modules_done = summary_node.attrib['modules_done']
                        if int(modules_total) > 0:
                            # treat job as not finished successfully when no modules to be reported
                            finished_successfully = True
                        else:
                            finished_successfully = False
                    except ET.ParseError as e:
                        logger.error('xml.etree.ElementTree.ParseError: %s' % e)
                        logger.info('Please Check %s manually' % result_file_path)
            except zipfile.BadZipFile:
                logger.info("File is not a zip file: %s" % result_file_path)

    elif job.get('job_status') == 'Complete':
        finished_successfully = True
    else:
        finished_successfully = False

    job['numbers'] = {
            'number_passed': int(job_number_passed),
            'number_failed': int(job_number_failed),
            'number_assumption_failure': int(job_number_assumption_failure),
            'number_ignored': int(job_number_ignored),
            'number_total': job_number_total,
            'modules_total': int(modules_total),
            'modules_done': int(modules_done),
            'finished_successfully': finished_successfully
            }

    return job['numbers']


def get_classified_jobs(jobs=[]):
    '''
        remove the resubmitted jobs and duplicated jobs(needs the jobs to be sorted in job_id descending order)
        as the result for the resubmit(including the duplicated jobs) jobs should be ignored.
    '''
    resubmitted_job_urls = [ job.get('parent_job') for job in jobs if job.get('parent_job')]
    job_names = []
    jobs_to_be_checked = []
    resubmitted_or_duplicated_jobs = []

    def get_job_external_url(item):
        external_url = item.get('external_url')
        if external_url:
            return external_url
        # when the job is not submitted to lava server, external_url will be None
        # unorderable types: NoneType() < NoneType()
        return ""

    # sorted with the job id in lava server
    # to get the latest jobs to use
    sorted_jobs = sorted(jobs, key=get_job_external_url, reverse=True)
    for job in sorted_jobs:
        if job.get('url') in resubmitted_job_urls:
            # ignore jobs which were resubmitted
            job['resubmitted'] = True
            resubmitted_or_duplicated_jobs.append(job)
            continue

        if job.get('name') in job_names:
            job['duplicated'] = True
            resubmitted_or_duplicated_jobs.append(job)
            continue

        jobs_to_be_checked.append(job)
        job_names.append(job.get('name'))

    return {
        'final_jobs': jobs_to_be_checked,
        'resubmitted_or_duplicated_jobs': resubmitted_or_duplicated_jobs,
        }


def get_test_result_number_for_build(build, jobs=None):
    test_numbers = qa_report.TestNumbers()

    if not jobs:
        jobs = get_jobs_for_build_from_db_or_qareport(build_id=build.get("id"), force_fetch_from_qareport=True)

    jobs_to_be_checked = get_classified_jobs(jobs=jobs).get('final_jobs')
    download_attachments_save_result(jobs=jobs_to_be_checked)

    jobs_finished = 0
    for job in jobs_to_be_checked:
        try:
            report_job = ReportJob.objects.get(job_url=job.get('external_url'))
            test_numbers.addWithDatabaseRecord(report_job)
            if report_job.finished_successfully:
                jobs_finished = jobs_finished + 1
        except ReportJob.DoesNotExist:
            # the job is not completed,
            # so no number would be calculated
            pass

    return {
        'number_passed': test_numbers.number_passed,
        'number_failed': test_numbers.number_failed,
        'number_assumption_failure': test_numbers.number_assumption_failure,
        'number_ignored': test_numbers.number_ignored,
        'number_total': test_numbers.number_total,
        'modules_done': test_numbers.modules_done,
        'modules_total': test_numbers.modules_total,
        'jobs_total': len(jobs_to_be_checked),
        'jobs_finished': jobs_finished,
        }


def get_lkft_build_status(build, jobs):
    if not jobs:
        jobs = get_jobs_for_build_from_db_or_qareport(build_id=build.get("id"), force_fetch_from_qareport=True)

    jobs_to_be_checked = get_classified_jobs(jobs=jobs).get('final_jobs')
    if isinstance(build.get('created_at'), str):
        last_fetched_timestamp = qa_report_api.get_aware_datetime_from_str(build.get('created_at'))
    else:
        last_fetched_timestamp = build.get('created_at')
    has_unsubmitted = False
    has_canceled = False
    is_inprogress = False
    for job in jobs_to_be_checked:
        if not job.get('submitted'):
            has_unsubmitted = True
            break
        if job.get('job_status') == 'Canceled':
            has_canceled = True
            break

        if job.get('fetched'):
            if job.get('fetched_at'):
                job_last_fetched_timestamp = qa_report_api.get_aware_datetime_from_str(job.get('fetched_at'))
                if job_last_fetched_timestamp > last_fetched_timestamp:
                    last_fetched_timestamp = job_last_fetched_timestamp
        else:
            is_inprogress = True
            break

    if has_unsubmitted:
        build['build_status'] = "JOBSNOTSUBMITTED"
    elif is_inprogress:
        build['build_status'] = "JOBSINPROGRESS"
    elif has_canceled:
        build['build_status'] = "CANCELED"
    else:
        build['build_status'] = "JOBSCOMPLETED"
        build['last_fetched_timestamp'] = last_fetched_timestamp

    return {
        'is_inprogress': is_inprogress,
        'has_unsubmitted': has_unsubmitted,
        'has_canceled': has_canceled,
        'last_fetched_timestamp': last_fetched_timestamp,
        }


def get_trigger_url_from_db_report_build(db_report_build):
    db_ci_trigger_build = db_report_build.ci_trigger_build
    trigger_ci_build_url = jenkins_api.get_job_url(name=db_ci_trigger_build.name, number=db_ci_trigger_build.number)
    return trigger_ci_build_url


def get_trigger_from_qareport_build(qareport_build):
    db_report_build = get_build_from_database_or_qareport(qareport_build.get('id'))[1]
    if db_report_build.ci_trigger_build and \
            db_report_build.ci_trigger_build.changes_num != 0 and \
            db_report_build.ci_trigger_build.display_name is not None :
        ci_trigger_build = {}
        ci_trigger_build['name'] = db_report_build.ci_trigger_build.name
        ci_trigger_build['number'] = db_report_build.ci_trigger_build.number
        ci_trigger_build['duration'] = db_report_build.ci_trigger_build.duration
        ci_trigger_build['result'] = db_report_build.ci_trigger_build.result
        ci_trigger_build['start_timestamp'] = db_report_build.ci_trigger_build.timestamp
        ci_trigger_build['displayName'] = db_report_build.ci_trigger_build.display_name
        ci_trigger_build['changes_num'] = db_report_build.ci_trigger_build.changes_num
        ci_trigger_build['url'] = jenkins_api.get_job_url(name=db_report_build.ci_trigger_build.name, number=db_report_build.ci_trigger_build.number)
        return ci_trigger_build

    build_meta = qa_report_api.get_build_meta_with_url(qareport_build.get('metadata'))
    if not build_meta:
        return None

    ci_build_url = build_meta.get("build-url")
    if not ci_build_url:
        return None
    elif type(ci_build_url)  == str:
        ci_build_url = ci_build_url
    elif type(ci_build_url)  == list:
        ci_build_url = ci_build_url[-1]
    else:
        # not sure what might be  here now
        pass

    # https://ci.linaro.org/job/lkft-hikey-android-10.0-gsi-4.19/119/
    ci_build_number = ci_build_url.strip('/').split('/')[-1]
    ci_build_name = ci_build_url.strip('/').split('/')[-2]
    db_ci_build = CiBuild.objects.get_or_create(name=ci_build_name, number=ci_build_number)[0]

    if not db_report_build.ci_build:
        db_report_build.ci_build = db_ci_build
        db_report_build.save()

    try:
        ci_build = jenkins_api.get_build_details_with_full_url(build_url=ci_build_url)
        db_ci_build.timestamp = qa_report_api.get_aware_datetime_from_timestamp(int(ci_build['timestamp'])/1000)
        db_ci_build.display_name = ci_build.get('displayName')
        if ci_build.get('building'):
            db_ci_build.result = 'INPROGRESS'
            db_ci_build.duration = datetime.timedelta(milliseconds=0).total_seconds()
        else:
            db_ci_build.result = ci_build.get('result')
            db_ci_build.duration =  datetime.timedelta(milliseconds=ci_build['duration']).total_seconds()
        db_ci_build.save()

    except UrlNotFoundException:
        db_ci_build.result = 'CI_BUILD_DELETED'
        db_ci_build.duration = datetime.timedelta(milliseconds=0).total_seconds()
        db_ci_build.display_name = "CI_BUILD_DELETED"
        db_ci_build.save()
        ci_build = None

    if ci_build:
        try:
            trigger_ci_build = jenkins_api.get_final_trigger_from_ci_build(ci_build)
            if trigger_ci_build is None:
                # the build might be deleted already
                return None
            trigger_ci_build_url = trigger_ci_build.get('url')
            trigger_ci_build_number = trigger_ci_build_url.strip('/').split('/')[-1]
            trigger_ci_build_name = trigger_ci_build_url.strip('/').split('/')[-2]

            db_trigger_ci_build = CiBuild.objects.get_or_create(name=trigger_ci_build_name, number=trigger_ci_build_number)[0]

            db_report_build.ci_trigger_build = db_trigger_ci_build
            db_report_build.save()

            if trigger_ci_build.get('building'):
                db_trigger_ci_build.result = 'INPROGRESS'
                db_trigger_ci_build.duration = datetime.timedelta(milliseconds=0).total_seconds()
            else:
                db_trigger_ci_build.result = ci_build.get('result')
                db_trigger_ci_build.duration =  datetime.timedelta(milliseconds=trigger_ci_build['duration']).total_seconds()

            change_items = []
            changes = trigger_ci_build.get('changeSet')
            if changes:
                change_items = changes.get('items')

            trigger_ci_build['changes_num'] = len(change_items)
            trigger_ci_build['start_timestamp'] = qa_report_api.get_aware_datetime_from_timestamp(int(trigger_ci_build['timestamp'])/1000)

            db_trigger_ci_build.timestamp = trigger_ci_build.get('start_timestamp')
            db_trigger_ci_build.display_name = trigger_ci_build.get('displayName')
            db_trigger_ci_build.changes_num = len(change_items)
            db_trigger_ci_build.save()

            return trigger_ci_build
        except UrlNotFoundException:
            return None
    else:
        return None


def get_project_info(project):

    logger.info("%s: Start to get qa-build information for project", project.get('name'))
    try:
        db_report_project = ReportProject.objects.get(project_id=int(project.get('id')))
    except ReportProject.DoesNotExist:
        db_report_project = None

    builds = qa_report_api.get_all_builds(project.get('id'), only_first=True)
    db_report_build = None
    if len(builds) > 0:
        last_build = builds[0]

        if db_report_project is not None:
            try:
                db_report_build = ReportBuild.objects.get(version=last_build.get('version'), qa_project=db_report_project)
            except ReportBuild.DoesNotExist:
                db_report_build = None
        else:
            db_report_build = None

        last_build['created_at'] = qa_report_api.get_aware_datetime_from_str(last_build.get('created_at'))
        jobs = get_jobs_for_build_from_db_or_qareport(build_id=last_build.get("id"), force_fetch_from_qareport=True)
        last_build['numbers_of_result'] = get_test_result_number_for_build(last_build, jobs)
        build_status = get_lkft_build_status(last_build, jobs)
        project['last_build'] = last_build

        trigger_ci_build_url = None
        if db_report_build:
            db_ci_build = db_report_build.ci_build
            last_build_ci_build_url = jenkins_api.get_job_url(name=db_ci_build.name, number=db_ci_build.number)
            trigger_ci_build_url =  get_trigger_url_from_db_report_build(db_report_build)
        else:
            last_build_meta = qa_report_api.get_build_meta_with_url(last_build.get('metadata'))
            last_build_ci_build_url = last_build_meta.get("build-url")

        if last_build_ci_build_url:
            last_build_ci_build = jenkins_api.get_build_details_with_full_url(build_url=last_build_ci_build_url)
            last_build_ci_build_start_timestamp = qa_report_api.get_aware_datetime_from_timestamp(int(last_build_ci_build['timestamp'])/1000)
            last_build_ci_build_duration = datetime.timedelta(milliseconds=last_build_ci_build['duration'])

            kernel_version = last_build_ci_build.get('displayName') # #buildNo.-kernelInfo
            if last_build_ci_build.get('building'):
                build_status = 'INPROGRESS'
            else:
                build_status = last_build_ci_build.get('result') # null or SUCCESS, FAILURE, ABORTED
            last_ci_build= {
                'build_status': build_status,
                'kernel_version': kernel_version,
                'ci_build_project_url':  last_build_ci_build_url,
                'duration': last_build_ci_build_duration,
                'start_timestamp': last_build_ci_build_start_timestamp,
            }
            project['last_ci_build'] = last_ci_build

            if not trigger_ci_build_url:
                trigger_ci_build = jenkins_api.get_final_trigger_from_ci_build(last_build_ci_build)
                if trigger_ci_build:
                    trigger_ci_build_url = trigger_ci_build.get('url')

        if trigger_ci_build_url:
            last_trigger_build = jenkins_api.get_build_details_with_full_url(build_url=trigger_ci_build_url)
            last_trigger_build['start_timestamp'] = qa_report_api.get_aware_datetime_from_timestamp(int(last_trigger_build['timestamp'])/1000)
            last_trigger_build['duration'] = datetime.timedelta(milliseconds=last_trigger_build['duration'])
            change_items = []
            changes = last_trigger_build.get('changeSet')
            if changes:
                change_items = changes.get('items')
            last_trigger_build['changes_num'] = len(change_items)
            project['last_trigger_build'] = last_trigger_build

    if project.get('last_build') and project.get('last_ci_build') and \
        project['last_build']['build_status'] == "JOBSCOMPLETED":
        last_ci_build = project.get('last_ci_build')
        last_build = project.get('last_build')
        if last_ci_build.get('start_timestamp'):
            project['duration'] = last_build.get('last_fetched_timestamp') - last_ci_build.get('start_timestamp')

    logger.info("%s: finished to get information for project", project.get('name'))


def thread_pool(func=None, elements=[]):
    subgroup_count = 10
    number_of_elements = len(elements)
    number_of_subgroup = math.ceil(number_of_elements/subgroup_count)
    finished_count = 0
    for i in range(number_of_subgroup):
        subgroup_elements = elements[i*subgroup_count: (i+1)*subgroup_count]
        finished_count = finished_count + len(subgroup_elements)

        threads = list()
        for element in subgroup_elements:
            t = threading.Thread(target=func, args=(element,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

    logger.info("Finished getting information for all elements: number_of_elements=%d, number_of_subgroup=%d, finished_count=%d" % (number_of_elements, number_of_subgroup, finished_count))


def is_project_accessible(project_full_name=None, user=AnonymousUser):
    if project_full_name is None:
        return False

    if user.is_superuser or user.is_staff:
        return True

    permissions = RESTRICTED_PROJECTS.get(project_full_name, None)
    if permissions:
        # this project is one restricted project
        for permission in permissions:
            if user.has_perm(permission):
                # the user has the permission specified
                return True
        # the user does not have any permission required to view the project
        return False
    else:
        # the project is not a restricted project, which means it is a public project
        # then return True
        return True


def get_projects_info(groups=[], request=None):
    group_hash = {}
    for group in groups:
        group_hash[group.get('group_name')] = group

    projects = []
    for project in qa_report_api.get_projects():
        if project.get('is_archived'):
            continue

        if request is not None and \
            not is_project_accessible(project_full_name=project.get('full_name'), user=request.user):
            # the current user has no permission to access the project
            continue

        group_name = project.get('full_name').split('/')[0]
        if not group_name in group_hash.keys():
            continue

        group = group_hash.get(group_name)
        group['qareport_url'] = project.get('group')
        group_projects = group.get('projects')
        if group_projects:
            group_projects.append(project)
        else:
            group['projects'] = [project]

        project['group'] = group

        projects.append(project)

    thread_pool(func=get_project_info, elements=projects)

    def get_project_name(item):
        return item.get('name')

    for group in groups:
        if group.get('projects'):
            sorted_projects = sorted(group['projects'], key=get_project_name)
            group['projects'] = sorted_projects
        else:
            group['projects'] = []

    return groups


def list_group_projects(request, groups=[], title_head="LKFT Projects", get_bugs=True):
    groups = get_projects_info(groups=groups, request=request)
    open_bugs = []
    if get_bugs:
        bugs = get_lkft_bugs()
        for bug in bugs:
            if bug.status == 'VERIFIED' or bug.status== 'RESOLVED':
                continue
            open_bugs.append(bug)

    response_data = {
        'open_bugs': open_bugs,
        'title_head': title_head,
        'groups': groups,
    }

    return render(request, 'lkft-projects.html', response_data)

def list_rc_projects(request):
    groups = [
                {
                    'group_name': 'android-lkft-rc',
                    'display_title': "RC Projects",
                },
            ]
    title_head = "LKFT RC Projects"
    return list_group_projects(request, groups=groups, title_head=title_head)

def list_boottime_projects(request):
    groups = [
                {
                    'group_name': 'android-lkft-benchmarks',
                    'display_title': "Boottime Projects",
                },
            ]

    title_head = "LKFT Boottime Projects"
    return list_group_projects(request, groups=groups, title_head=title_head, get_bugs=False)

def list_projects(request):
    groups = [
                {
                    'group_name': 'android-lkft',
                    'display_title': "LKFT Projects",
                },
                # {
                #     'group_name': 'android-lkft-benchmarks',
                #     'display_title': "Benchmark Projects",
                # },
                # {
                #     'group_name': 'android-lkft-rc',
                #     'display_title': "RC Projects",
                # },
            ]

    title_head = "LKFT Projects"
    return list_group_projects(request, groups=groups, title_head=title_head)


def get_build_info(db_reportproject=None, build=None, fetch_latest_from_qa_report=False):
    if not build:
        return

    logger.info("Start getting information for build: %s %s", build.get('version'), build.get('build_status'))
    db_report_build = None
    if db_reportproject:
        try:
            db_report_build = ReportBuild.objects.get(version=build.get('version'), qa_project=db_reportproject)
        except ReportBuild.DoesNotExist:
            pass

    jobs = get_jobs_for_build_from_db_or_qareport(build_id=build.get("id"), force_fetch_from_qareport=fetch_latest_from_qa_report)

    if not fetch_latest_from_qa_report and db_report_build and db_report_build.finished:
        build.update(get_build_from_database(db_report_build))
    else:
        build['created_at'] = qa_report_api.get_aware_datetime_from_str(build.get('created_at'))

    trigger_build = get_trigger_from_qareport_build(build)

    get_lkft_build_status(build, jobs)
    build['numbers'] = get_test_result_number_for_build(build, jobs)

    if trigger_build:
        trigger_build['duration'] = datetime.timedelta(milliseconds=trigger_build['duration'])
        build['trigger_build'] = {
            'name': trigger_build.get('name'),
            'url': trigger_build.get('url'),
            'displayName': trigger_build.get('displayName'),
            'start_timestamp': trigger_build.get('start_timestamp'),
            'changes_num': trigger_build.get('changes_num'),
        }

    if  build['build_status'] == "JOBSCOMPLETED":
        if trigger_build and trigger_build.get('start_timestamp'):
            build['duration'] = build.get('last_fetched_timestamp') - trigger_build.get('start_timestamp')
        else:
            build['duration'] = build.get('last_fetched_timestamp') - build.get('created_at')

    logger.info("Finished getting information for build: %s %s", build.get('version'), build.get('build_status'))
    return build



def cache_qaproject_to_database(target_project):
    db_report_project = ReportProject.objects.get_or_create(project_id=target_project.get('id'))[0]
    db_report_project.group = qa_report_api.get_project_group(target_project)
    db_report_project.name = target_project.get('name')
    db_report_project.slug = target_project.get('slug')
    db_report_project.is_public = target_project.get('is_public')
    db_report_project.is_archived = target_project.get('is_archived')
    db_report_project.save()

    return db_report_project


def cache_qabuild_to_database(qareport_build):
    db_report_build, created = ReportBuild.objects.get_or_create(qa_build_id=qareport_build.get('id'))
    if created or db_report_build.metadata_url is None or not db_report_build.finished:
        db_report_build.version = qareport_build.get('version')
        db_report_build.metadata_url = qareport_build.get('metadata')
        db_report_build.started_at = qareport_build.get('created_at')
        db_report_build.finished = qareport_build.get('finished')
        if qareport_build.get('last_fetched_timestamp'):
            db_report_build.fetched_at = qareport_build.get('last_fetched_timestamp')

        if db_report_build.qa_project is None:
            target_project_id = qareport_build.get('project').strip('/').split('/')[-1]
            db_report_project = get_project_from_database_or_qareport(target_project_id)[1]
            db_report_build.qa_project = db_report_project

        if qareport_build.get('build_status'):
            db_report_build.status = qareport_build.get('build_status')

        db_report_build.save()
    return db_report_build


def cache_qajob_to_database(job):
    report_job = ReportJob.objects.get_or_create(job_url=job.get('external_url'))[0]

    report_job.job_name = job.get('name')
    report_job.qa_job_id = job.get('id')
    report_job.attachment_url = job.get('attachment_url')
    report_job.parent_job = job.get('parent_job')
    report_job.environment = job.get('environment')
    report_job.status = job.get('job_status') # all possible status: Submitted, Running, Complete, Incomplete, Canceled
    if report_job.failure_msg is None and job.get('failure') and job.get('failure').get('error_msg'):
        report_job.failure_msg = job.get('failure').get('error_msg')

    if report_job.submitted_at is None:
        if job.get('submitted_at'):
            submitted_at = qa_report_api.get_aware_datetime_from_str(job.get('submitted_at'))
            report_job.submitted_at = submitted_at
        elif job.get('created_at'):
            submitted_at = qa_report_api.get_aware_datetime_from_str(job.get('created_at'))
            report_job.submitted_at = submitted_at
        else:
            # something is wrong here without neither submitted_at nor created_at
            pass

    if report_job.fetched_at is None and job.get('fetched_at'):
        fetched_at = qa_report_api.get_aware_datetime_from_str(job.get('fetched_at'))
        report_job.fetched_at = fetched_at

    if report_job.report_build is None:
        target_build_id = job.get('target_build').strip('/').split('/')[-1]
        db_report_build =  get_build_from_database_or_qareport(target_build_id)[1]
        report_job.report_build = db_report_build

    if job.get('resubmitted'):
        resubmitted = job.get('resubmitted')
        report_job.resubmitted = resubmitted

    if not report_job.results_cached and \
            job.get('numbers') is not None:
        qa_report.TestNumbers.setHashValueForDatabaseRecord(report_job, report_job. job.get('numbers'))
        report_job.results_cached = True
        report_job.finished_successfully = True

    report_job.save()

    return report_job


def get_project_from_database_or_qareport(project_id, force_fetch_from_qareport=False):
    try:
        db_reportproject = ReportProject.objects.get(project_id=project_id)
    except ReportProject.DoesNotExist:
        db_reportproject = None

    if not force_fetch_from_qareport and db_reportproject is not None:
        target_project = {
                'full_name': "%s/%s" % (db_reportproject.group, db_reportproject.slug),
                'id': project_id,
                'name': db_reportproject.name,
                'slug': db_reportproject.slug,
                'is_archived': db_reportproject.is_archived,
                'is_public': db_reportproject.is_public,
              }
    else:
        target_project =  qa_report_api.get_project(project_id)
        db_report_project = cache_qaproject_to_database(target_project)

    return (target_project, db_reportproject)


def get_builds_from_database_or_qareport(project_id, db_reportproject, force_fetch_from_qareport=False):
    needs_fetch_builds_from_qareport = False
    builds = []
    if not force_fetch_from_qareport and db_reportproject:
        db_report_builds = ReportBuild.objects.filter(qa_project=db_reportproject).order_by('-qa_build_id')
        if len(db_report_builds) > 0:
            for db_report_build in db_report_builds:
                build = get_build_from_database(db_report_build)
                # if not db_report_build.finished:
                #     needs_fetch_builds_from_qareport = True
                #     break
                # else:
                builds.append(build)
        else:
            needs_fetch_builds_from_qareport = True

    if force_fetch_from_qareport or needs_fetch_builds_from_qareport:
        builds = qa_report_api.get_all_builds(project_id)
        for build in builds:
            cache_qabuild_to_database(build)

    return builds


def get_build_from_database(db_report_build):
    build = {}
    build['id'] = db_report_build.qa_build_id
    build['version'] = db_report_build.version
    build['project'] = qa_report_api.get_project_api_url_with_project_id(db_report_build.qa_project.project_id)
    build['created_at'] = db_report_build.started_at
    build['build_status'] = db_report_build.status
    build['last_fetched_timestamp'] = db_report_build.fetched_at
    build['metadata'] = db_report_build.metadata_url
    build['finished'] = db_report_build.finished

    return build


def get_build_from_database_or_qareport(build_id, force_fetch_from_qareport=False):
    qareport_build = {}
    try:
        db_report_build = ReportBuild.objects.get(qa_build_id=build_id)
    except ReportBuild.DoesNotExist:
        db_report_build = None

    if not force_fetch_from_qareport and \
            db_report_build is not None and \
            db_report_build.metadata_url is not None and \
            db_report_build.qa_project is not None :
        qareport_build = get_build_from_database(db_report_build)
    else:
        qareport_build = qa_report_api.get_build(build_id)
        db_report_build = cache_qabuild_to_database(qareport_build)

    return (qareport_build, db_report_build)


def get_jobs_for_build_from_db_or_qareport(build_id=None, force_fetch_from_qareport=False):
    needs_fetch_jobs = False

    try:
        db_report_build = ReportBuild.objects.get(qa_build_id=build_id)
    except ReportBuild.DoesNotExist:
        needs_fetch_jobs = True
        db_report_build = None

    jobs = []
    if not force_fetch_from_qareport and db_report_build is not None :
        db_report_jobs = ReportJob.objects.filter(report_build=db_report_build)
        if len(db_report_jobs) == 0:
            logger.info("No jobs found for build: %s", build_id)
            needs_fetch_jobs = True
        else:
            for db_report_job in db_report_jobs:
                job = {}
                job['external_url'] = db_report_job.job_url
                job['name'] = db_report_job.job_name
                job['attachment_url'] = db_report_job.attachment_url
                job['id'] = db_report_job.qa_job_id
                job['parent_job'] = db_report_job.parent_job
                job['job_status'] = db_report_job.status
                job['environment'] = db_report_job.environment
                job['target'] = qa_report_api.get_project_api_url_with_project_id(db_report_job.report_build.qa_project.project_id)
                job['target_build'] = qa_report_api.get_build_api_url_with_build_id(db_report_job.report_build.qa_build_id)
                job['submitted'] = True
                job['submitted_at'] = db_report_job.submitted_at
                if db_report_job.fetched_at:
                    job['fetched'] = True
                    job['fetched_at'] = db_report_job.fetched_at

                job['job_id'] = qa_report_api.get_qa_job_id_with_url(db_report_job.job_url)
                lava_config = find_lava_config(db_report_job.job_url)
                if lava_config:
                    job['lava_config'] = lava_config

                if db_report_job.failure_msg:
                    job['failure'] = {'error_msg': db_report_job.failure_msg}
                jobs.append(job)

    if force_fetch_from_qareport or needs_fetch_jobs:
        jobs = qa_report_api.get_jobs_for_build(build_id)
        get_attachment_urls(jobs)
        for job in jobs:
            cache_qajob_to_database(job)

    return jobs


def get_measurements_of_project(project_id=None, project_name=None, project_group=None, project=None, builds=[], benchmark_jobs=[], testsuites=[], testcases=[], fetch_latest_from_qa_report=False):
    # if project_id is not None:
    #     db_report_project = ReportProject.objects.get(project_id=project_id)
    # elif project_group is None:
    #     db_report_project = ReportProject.objects.get(name=project_name)
    # else:
    #     db_report_project = ReportProject.objects.get(group=project_group, name=project_name)

    # db_report_builds = ReportBuild.objects.filter(qa_project=db_report_project)
    if project is not None:
        local_project = project
    else:
        local_project = qa_report_api.get_project(project_id)
    project_full_name = local_project.get('full_name')
    if project_full_name.find("android-lkft-benchmarks") < 0:
        return {}

    if builds and len(builds) > 0:
        local_builds = builds
    else:
        local_builds = qa_report_api.get_all_builds(local_project.get('id'))

    benchmark_tests = get_expected_benchmarks()
    expected_benchmark_jobs = sorted(benchmark_tests.keys())
    if benchmark_jobs and len(benchmark_jobs) > 0:
        expected_benchmark_jobs = benchmark_jobs

    allbenchmarkjobs_result_dict = {}
    # for db_report_build in db_report_builds:
    for build in local_builds[:BUILD_WITH_JOBS_NUMBER]:
        jobs = get_jobs_for_build_from_db_or_qareport(build_id=build.get("id"), force_fetch_from_qareport=fetch_latest_from_qa_report)
        jobs_to_be_checked = get_classified_jobs(jobs=jobs).get('final_jobs')
        download_attachments_save_result(jobs_to_be_checked)

        for benchmark_job_name in expected_benchmark_jobs:
            target_job = None
            for job in jobs_to_be_checked:
                if job.get('name').endswith(benchmark_job_name):
                    target_job = job
                    break

            if target_job is None:
                continue

            onebuild_onejob_testcases_res = []
            onejob_testcases = []
            test_suites = benchmark_tests.get(benchmark_job_name)
            expected_testsuites = sorted(test_suites.keys())
            if testsuites and len(testsuites) > 0:
                expected_testsuites = testsuites
            for testsuite in expected_testsuites:
                expected_testcases = test_suites.get(testsuite)
                if testcases and len(testcases) > 0:
                    expected_testcases = testcases
                for testcase in expected_testcases:
                    testsuite_testcase = "%s#%s" % (testsuite, testcase)
                    if testsuite_testcase not in onejob_testcases:
                        onejob_testcases.append(testsuite_testcase)
                    # which is actually ordered by the job id
                    # final_jobs = ReportJob.objects.filter(report_build=db_report_build, resubmitted=False, status='Complete', job_name__endswith='-%s' % benchmark_job_name).order_by('job_url')
                    # if final_jobs.count() <= 0:

                    if target_job is None:
                        # theere isn't any job finished successfully
                        unit = '--'
                        measurement = '--'
                        job_lava_id = '--'
                        job_lava_url = '--'
                        lava_nick = '--'
                    else:
                        # only use the result from the latest job
                        # final_job = final_jobs[-1]
                        # job_lava_id = qa_report_api.get_qa_job_id_with_url(final_job.job_url)
                        # lava_nick = find_lava_config(final_job.job_url).get('nick')
                        job_lava_id = target_job.get('job_id')
                        lava_nick = target_job.get('lava_config').get('nick')
                        job_lava_url = target_job.get('external_url')
                        try:
                            test_case_res = TestCase.objects.get(job_id=job_lava_id, lava_nick=lava_nick, suite__endswith='_%s' % testsuite, name=testcase)
                            unit = test_case_res.unit
                            measurement = test_case_res.measurement
                        except TestCase.DoesNotExist:
                            if benchmark_job_name == "boottime":
                                if testsuite == 'boottime-fresh-install':
                                    test_cases = TestCase.objects.filter(job_id=job_lava_id, lava_nick=lava_nick, suite__endswith='_%s' % "boottime-first-analyze", name=testcase)
                                elif testsuite == 'boottime-reboot':
                                    test_cases = TestCase.objects.filter(job_id=job_lava_id, lava_nick=lava_nick, suite__endswith='_%s' % "boottime-second-analyze", name=testcase)
                                else:
                                    test_cases = []
                            else:
                                test_cases = []

                            if len(test_cases) > 0:
                                test_case_res = test_cases[0]
                                unit = test_case_res.unit
                                measurement = test_case_res.measurement
                            else:
                                unit = '--'
                                measurement = '--'

                    onebuild_onejob_testcases_res.append({
                        'unit': unit,
                        'measurement': measurement,
                        'testcase': testcase,
                        'testsuite': testsuite,
                        # 'build_version': db_report_build.version,
                        'build_version': build.get('version'),
                        'qa_build_id': build.get('id'),
                        'job_lava_id': job_lava_id,
                        'job_lava_url': job_lava_url,
                        'lava_nick': lava_nick,
                        })

            onebuild_onejob_result = {
                "build_no": build.get('version'),
                "qa_build_id": build.get('id'),
                "project_full_name": project_full_name,
                'test_cases_res': onebuild_onejob_testcases_res,
                }

            benchmark_job_results = allbenchmarkjobs_result_dict.get(benchmark_job_name)
            if benchmark_job_results is None:
                allbenchmarkjobs_result_dict[benchmark_job_name] = {
                        'benchmark_job_name': benchmark_job_name,
                        'trend_data': [onebuild_onejob_result],
                        'all_testcases': onejob_testcases,
                    }
            else:
                benchmark_job_results.get('trend_data').append(onebuild_onejob_result)
    return allbenchmarkjobs_result_dict


def list_builds(request):
    project_id = request.GET.get('project_id', None)
    fetch_latest_from_qa_report = request.GET.get('fetch_latest', "false").lower() == 'true'

    logger.info("Start for list_builds: %s" % project_id)

    project, db_reportproject = get_project_from_database_or_qareport(project_id, force_fetch_from_qareport=fetch_latest_from_qa_report)
    project_full_name = project.get('full_name')
    if not is_project_accessible(project_full_name=project_full_name, user=request.user):
        # the current user has no permission to access the project
        return render(request, '401.html', status=401)

    logger.info("Start for list_builds before get_builds_from_database_or_qareport: %s" % project_id)
    builds = get_builds_from_database_or_qareport(project_id, db_reportproject, force_fetch_from_qareport=fetch_latest_from_qa_report)

    logger.info("Start for list_builds before loop of get_build_info: %s" % project_id)
    builds_result = []
    if project_full_name.find("android-lkft-benchmarks") < 0:
        for build in builds[:BUILD_WITH_JOBS_NUMBER]:
            builds_result.append(get_build_info(db_reportproject, build, fetch_latest_from_qa_report=fetch_latest_from_qa_report))

        #func = functools.partial(get_build_info, db_reportproject)
        #with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
        #    builds_result = list(executor.map(func, builds[:BUILD_WITH_JOBS_NUMBER]))

    #   ## The following two method cause Segmentation fault (core dumped)
    #   ## Sep 23 11:01:18 laptop kernel: [13401.895696] traps: python[26374] general protection fault ip:7f7e62987ac2 sp:7f7e6113b3f0 error:0 in _queue.cpython-37m-x86_64-linux-gnu.so[7f7e62987000+1000]
    #    with multiprocessing.Pool(10) as pool:
    #        pool.map(func, builds_result)
    #    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    #        executor.map(func, builds_result)

        benchmark_jobs_data_dict = {}
        boottime_jobs_data = None

    else:
        benchmark_jobs_data_dict = get_measurements_of_project(project=project, builds=builds, fetch_latest_from_qa_report=fetch_latest_from_qa_report)

        boottime_jobs_data_dict = benchmark_jobs_data_dict.pop('boottime', None)
        if boottime_jobs_data_dict:
            boottime_jobs_data = [boottime_jobs_data_dict]
        else:
            boottime_jobs_data = None

    logger.info("End for list_builds: %s" % project_id)

    return render(request, 'lkft-builds.html',
                           {
                                "builds": builds_result,
                                'project': project,
                                "benchmark_jobs_data": benchmark_jobs_data_dict.values(),
                                "boottime_jobs_data": boottime_jobs_data,
                                'fetch_latest': fetch_latest_from_qa_report,
                            })


def get_lkft_bugs(summary_keyword=None, platform=None):
    bugs = []

    terms = [
                {u'product': 'Linaro Android'},
                {u'component': 'General'},
                {u'op_sys': 'Android'},
                {u'keywords': 'LKFT'}
            ]
    if platform is not None:
        terms.append({u'platform': platform})

    for bug in bugzilla_instance.search_bugs(terms).bugs:
        bug_dict = bugzilla.DotDict(bug)
        if summary_keyword is not None and \
            bug_dict.get('summary').find(summary_keyword) < 0:
            continue
        bugs.append(bug_dict)

    def get_bug_summary(item):
        return item.get('summary')

    sorted_bugs = sorted(bugs, key=get_bug_summary)
    return sorted_bugs


def find_bug_for_failure(failure, patterns=[], bugs=[]):
    found_bug = None
    for pattern in patterns:
        if found_bug is not None:
            break
        for bug in bugs:
            if pattern.search(bug.summary):
                if failure.get('bugs'):
                    failure['bugs'].append(bug)
                else:
                    failure['bugs'] = [bug]
                found_bug = bug
            if found_bug is not None:
                break

    return found_bug


def get_project_jobs(project):
    local_all_final_jobs = []
    local_all_resubmitted_jobs = []
    logger.info('Start to get jobs for project: {}'.format(project.get('full_name')))
    builds = qa_report_api.get_all_builds(project.get('id'), only_first=True)
    if len(builds) > 0:
        last_build = builds[0]
        jobs = get_jobs_for_build_from_db_or_qareport(build_id=last_build.get("id"), force_fetch_from_qareport=True)
        classified_jobs = get_classified_jobs(jobs=jobs)

        for job in classified_jobs.get('final_jobs'):
            job['qareport_build'] = last_build
            job['qareport_project'] = project
            local_all_final_jobs.append(job)

        for job in classified_jobs.get('resubmitted_or_duplicated_jobs'):
            job['qareport_build'] = last_build
            job['qareport_project'] = project
            local_all_resubmitted_jobs.append(job)

        project['last_build'] = last_build
        project['all_final_jobs'] = local_all_final_jobs
        project['all_resubmitted_jobs'] = local_all_resubmitted_jobs
    else:
        project['last_build'] = None
        project['all_final_jobs'] = []
        project['all_resubmitted_jobs'] = []

    logger.info('Finished to get jobs for project: {}'.format(project.get('full_name')))


@login_required
@permission_required('lkft.admin_projects')
def list_all_jobs(request):
    import threading
    threads = list()

    projects = []
    for project in qa_report_api.get_projects():
        project_full_name = project.get('full_name')
        if project.get('is_archived'):
            continue
        project['group_name'] = qa_report_api.get_project_group(project)

        if not project_full_name.startswith("android-lkft/") \
                and not project_full_name.startswith("android-lkft-benchmarks/") \
                and not project_full_name.startswith("android-lkft-rc/"):
            continue

        if not is_project_accessible(project_full_name=project.get('full_name'), user=request.user):
            continue

        projects.append(project)
        t = threading.Thread(target=get_project_jobs, args=(project,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    all_final_jobs = []
    all_resubmitted_jobs = []
    for project in projects:
        if project.get('last_build'):
            all_final_jobs.extend(project.get('all_final_jobs'))
            all_resubmitted_jobs.extend(project.get('all_resubmitted_jobs'))

    def get_key(item):
        project_full_name = item.get('qareport_project').get('full_name')
        build_name = item.get('qareport_build').get('version')
        job_name = item.get('name')
        job_lava_id = qa_report_api.get_qa_job_id_with_url(item.get('external_url'))
        return "{}#{}#{}#{}".format(project_full_name, build_name, job_name, job_lava_id)

    sorted_final_jobs = sorted(all_final_jobs, key=get_key)
    sorted_resubmitted_jobs = sorted(all_resubmitted_jobs, key=get_key)

    return render(request, 'lkft-all-jobs.html',
                           {
                                'all_final_jobs': sorted_final_jobs,
                                'all_resubmitted_jobs': sorted_resubmitted_jobs,
                            }
                )


def list_jobs(request):
    build_id = request.GET.get('build_id', None)
    fetch_latest_from_qa_report = request.GET.get('fetch_latest', "false").lower() == 'true'

    build, db_report_build =  get_build_from_database_or_qareport(build_id, force_fetch_from_qareport=fetch_latest_from_qa_report)
    project_id = build.get('project').strip('/').split('/')[-1]
    project, db_reportproject = get_project_from_database_or_qareport(project_id, force_fetch_from_qareport=fetch_latest_from_qa_report)
    project_full_name = project.get('full_name')
    if not is_project_accessible(project_full_name=project_full_name, user=request.user):
        # the current user has no permission to access the project
        return render(request, '401.html', status=401)

    project_name = project.get('name')

    jobs = get_jobs_for_build_from_db_or_qareport(build_id=build_id, force_fetch_from_qareport=fetch_latest_from_qa_report)
    classified_jobs = get_classified_jobs(jobs=jobs)
    jobs_to_be_checked = classified_jobs.get('final_jobs')
    resubmitted_duplicated_jobs = classified_jobs.get('resubmitted_or_duplicated_jobs')

    download_attachments_save_result(jobs=jobs)
    failures = {}
    resubmitted_job_urls = []
    benchmarks_res = []
    for job in jobs_to_be_checked:
        job['qa_job_id'] = job.get('id')
        short_desc = "%s: %s job failed to get test result with %s" % (project_name, job.get('name'), build.get('version'))
        new_bug_url = '%s&rep_platform=%s&version=%s&short_desc=%s' % ( bugzilla_instance.get_new_bug_url_prefix(),
                                                                          get_hardware_from_pname(pname=project_name, env=job.get('environment')),
                                                                          get_version_from_pname(pname=project_name),
                                                                          short_desc)
        job['new_bug_url'] = new_bug_url

        if is_benchmark_job(job.get('name')):
            expected_testsuites = get_benchmark_testsuites(job.get('name'))
            # local_job_name = job.get("name").replace("%s-%s-" % (build_name, build_no), "")
            # job["name"] = local_job_name
            # job["lava_nick"] = lava.nick
            lava_nick = job.get('lava_config').get('nick')
            job_id = job.get('job_id')
            job_name = job.get('name')

            for test_suite in sorted(expected_testsuites.keys()):
                test_cases = expected_testsuites.get(test_suite)
                for test_case in test_cases:
                    try:
                        test_case_res = TestCase.objects.get(job_id=job_id, lava_nick=lava_nick, suite__endswith='_%s' % test_suite, name=test_case)
                        unit = test_case_res.unit
                        measurement = test_case_res.measurement
                    except TestCase.DoesNotExist:
                        unit = '--'
                        measurement = '--'

                    benchmarks_res.append({'job_name': job_name,
                                           'job_id': job_id,
                                           'job_external_url': job.get('external_url'),
                                           'lava_nick': lava_nick,
                                           'test_case': test_case,
                                           'test_suite': test_suite,
                                           'unit': unit,
                                           'measurement': measurement,
                                          })
            continue # to check the next job
        else:
            # for cts/vts jobs

            result_file_path = get_result_file_path(job=job)
            if not result_file_path or not os.path.exists(result_file_path):
                continue

            kernel_version = get_kver_with_pname_env(prj_name=project_name, env=job.get('environment'))

            platform = job.get('environment').split('_')[0]

            metadata = {
                'job_id': job.get('job_id'),
                'qa_job_id': job.get('id'),
                'result_url': job.get('attachment_url'),
                'lava_nick': job.get('lava_config').get('nick'),
                'kernel_version': kernel_version,
                'platform': platform,
                }
            numbers = extract(result_file_path, failed_testcases_all=failures, metadata=metadata)
            job['numbers'] = numbers

    bugs = get_lkft_bugs(summary_keyword=project_name, platform=get_hardware_from_pname(project_name))
    bugs_reproduced = []
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

            failures_list.append(failure)

            if test_name.find(module_name) >=0:
                # vts test, module name is the same as the test name.
                search_key = test_name
            else:
                search_key = '%s %s' % (module_name, test_name)
            search_key_exact = search_key.replace('#arm64-v8a', '').replace('#armeabi-v7a', '')

            pattern_testcase = re.compile(r'\b({0})\s+failed\b'.format(search_key_exact.replace('[', '\[').replace(']', '\]')))
            pattern_testclass = re.compile(r'\b({0})\s+failed\b'.format(failure.get('test_class').replace('[', '\[').replace(']', '\]')))
            pattern_module = re.compile(r'\b({0})\s+failed\b'.format(module_name.replace('[', '\[').replace(']', '\]')))
            patterns = [pattern_testcase, pattern_testclass, pattern_module]
            found_bug = find_bug_for_failure(failure, patterns=patterns, bugs=bugs)
            if found_bug is not None:
                bugs_reproduced.append(found_bug)

    android_version = get_version_from_pname(pname=project.get('name'))
    open_bugs = []
    bugs_not_reproduced = []
    for bug in bugs:
        if bug.status == 'VERIFIED' or (bug.status == 'RESOLVED' and bug.resolution != 'WONTFIX'):
            continue
        if bug.version != android_version:
            continue
        if bug in bugs_reproduced:
            open_bugs.append(bug)
        else:
            bugs_not_reproduced.append(bug)

    # sort failures
    for module_name, failures_in_module in failures.items():
        failures[module_name] = collections.OrderedDict(sorted(failures_in_module.items()))
    failures = collections.OrderedDict(sorted(failures.items()))

    def get_job_name(item):
        if item.get('name'):
            return item.get('name')
        else:
            return ""

    final_jobs = sorted(jobs_to_be_checked, key=get_job_name)
    failed_jobs = sorted(resubmitted_duplicated_jobs, key=get_job_name)

    return render(request, 'lkft-jobs.html',
                           {
                                'final_jobs': final_jobs,
                                'failed_jobs': failed_jobs,
                                'build': build,
                                'failures': failures,
                                'failures_list': failures_list,
                                'open_bugs':open_bugs,
                                'bugs_not_reproduced': bugs_not_reproduced,
                                'project': project,
                                'bugzilla_show_bug_prefix': bugzilla_show_bug_prefix,
                                'benchmarks_res': benchmarks_res,
                                'fetch_latest': fetch_latest_from_qa_report,
                            }
                )


def get_bug_hardware_from_environment(environment):
    if environment.find('hi6220-hikey')>=0:
        return 'HiKey'
    else:
        return None

class BugCreationForm(forms.Form):
    project_name = forms.CharField(label='Project Name', widget=forms.TextInput(attrs={'size': 80}))
    project_id = forms.CharField(label='Project Id.')
    build_version = forms.CharField(label='Build Version', widget=forms.TextInput(attrs={'size': 80}))
    build_id = forms.CharField(label='Build Id.')
    product = forms.CharField(label='Product', widget=forms.TextInput(attrs={'readonly': True}))
    component = forms.CharField(label='Component', widget=forms.TextInput(attrs={'readonly': True}))
    version = forms.CharField(label='Version', widget=forms.TextInput(attrs={'readonly': True}) )
    os = forms.CharField(label='Os', widget=forms.TextInput(attrs={'readonly': True}))
    hardware = forms.CharField(label='Hardware', widget=forms.TextInput(attrs={'readonly': True}))
    severity = forms.CharField(label='Severity')
    keywords = forms.CharField(label='keywords')
    summary = forms.CharField(label='Summary', widget=forms.TextInput(attrs={'size': 80}))
    description = forms.CharField(label='Description', widget=forms.Textarea(attrs={'cols': 80}))

@login_required
@permission_required('lkft.admin_projects')
def file_bug(request):
    submit_result = False
    if request.method == 'POST':
        form = BugCreationForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data

            bug = bugzilla.DotDict()
            bug.product = cd['product']
            bug.component = cd['component']
            bug.summary = cd['summary']
            bug.description = cd['description']
            bug.bug_severity = cd['severity']
            bug.op_sys = cd['os']
            bug.platform = cd['hardware']
            bug.version = cd['version']
            bug.keywords = cd['keywords']

            bug_id = bugzilla_instance.post_bug(bug).id
            bug_info = {
                           'bugzilla_show_bug_prefix': bugzilla_show_bug_prefix,
                           'bug_id': bug_id,
                        }
            submit_result = True
            return render(request, 'lkft-file-bug.html',
                          {
                            "submit_result": submit_result,
                            'bug_info': bug_info,
                            'form': form,
                          })

        else:
            # not possible here since all are selectable elements
            return render(request, 'lkft-file-bug.html',
                      {
                        "form": form,
                        'submit_result': False,
                      })
    else: # GET
        project_name = request.GET.get("project_name")
        project_id = request.GET.get("project_id")
        build_id = request.GET.get("build_id")
        qa_job_ids_str = request.GET.get("qa_job_ids")
        module_name = request.GET.get("module_name")
        test_name = request.GET.get("test_name")

        qa_job_ids_tmp = qa_job_ids_str.split(',')
        qa_job_ids = []
        qa_jobs = []
        # remove the duplicate job_ids
        target_build = None
        for qa_job_id in qa_job_ids_tmp:
            if not qa_job_id in qa_job_ids:
                qa_job_ids.append(qa_job_id)
                #https://qa-reports.linaro.org/api/testjobs/1319604/?format=json
                qa_job = qa_report_api.get_job_with_id(qa_job_id)
                if qa_job is not None:
                    qa_jobs.append(qa_job)
                if target_build is None:
                    target_build = qa_job.get('target_build')
                elif target_build != qa_job.get('target_build'):
                    # need to make sure all the jobs are belong to the same build
                    # otherwise there is no meaning to list failures from jobs belong to different builds
                    # TODO : report error on webpage
                    logger.error("The jobs are belong to different builds: %s" % (qa_job_ids_str))

        project =  qa_report_api.get_project_with_url(qa_jobs[0].get('target'))
        build = qa_report_api.get_build_with_url(qa_jobs[0].get('target_build'))
        build_meta = qa_report_api.get_build_meta_with_url(build.get('metadata'))

        # download all the necessary attachments
        download_attachments_save_result(jobs=qa_jobs)

        pname = project.get('name')
        form_initial = {
                        "project_name": pname,
                        "project_id": project.get('id'),
                        'build_version': build.get('version'),
                        'build_id': build.get('id'),
                        'product': 'Linaro Android',
                        'component': 'General',
                        'severity': 'normal',
                        'os': 'Android',
                        'hardware': get_hardware_from_pname(pname=pname, env=qa_jobs[0].get('environment')),
                        'keywords': 'LKFT',
                        'version': get_version_from_pname(pname=pname),
                        }


        def extract_abi_stacktrace(result_zip_path, module_name='', test_name=''):

            failures = {}
            class_method = test_name.split('#')
            with zipfile.ZipFile(result_zip_path, 'r') as f_zip_fd:
                try:
                    root = ET.fromstring(remove_xml_unsupport_character(f_zip_fd.read(TEST_RESULT_XML_NAME).decode('utf-8')))
                    for elem in root.findall('.//Module[@name="%s"]' %(module_name)):
                        abi = elem.attrib['abi']
                        stacktrace_node = elem.find('.//TestCase[@name="%s"]/Test[@name="%s"]/Failure/StackTrace' %(class_method[0], class_method[1]))
                        if stacktrace_node is None:
                            # Try for VtsHal test cases
                            if abi == 'arm64-v8a':
                                stacktrace_node = elem.find('.//TestCase[@name="%s"]/Test[@name="%s_64bit"]/Failure/StackTrace' %(class_method[0], class_method[1]))
                            elif abi == 'armeabi-v7a':
                                stacktrace_node = elem.find('.//TestCase[@name="%s"]/Test[@name="%s_32bit"]/Failure/StackTrace' %(class_method[0], class_method[1]))

                        if stacktrace_node is not None:
                            failures[abi] = stacktrace_node.text
                        else:
                            logger.warn('failure StackTrace Node not found for module_name=%s, test_name=%s, abi=%s in file:%s' % (module_name, test_name, abi, result_zip_path))

                except ET.ParseError as e:
                    logger.error('xml.etree.ElementTree.ParseError: %s' % e)
                    logger.info('Please Check %s manually' % result_zip_path)
            return failures

        abis = []
        stacktrace_msg = None
        failures = {}
        failed_kernels = []
        for qa_job in qa_jobs:
            lava_job_id = qa_job.get('job_id')
            lava_url = qa_job.get('external_url')
            if not lava_url:
                logger.error('Job seems not submitted yet: '% job.get('url'))
                continue
            lava_config = find_lava_config(lava_url)
            result_file_path = get_result_file_path(qa_job)

            kernel_version = get_kver_with_pname_env(prj_name=project.get('name'), env=qa_job.get('environment'))

            qa_job['kernel_version'] = kernel_version
            job_failures = extract_abi_stacktrace(result_file_path, module_name=module_name, test_name=test_name)
            failures.update(job_failures)
            if not kernel_version in failed_kernels:
                # assuming the job specified mush have the failure for the module and test
                failed_kernels.append(kernel_version)

        abis = sorted(failures.keys())
        stacktrace_msg = ''
        if len(abis) == 0:
            logger.error('Failed to get stacktrace information for %s %s form jobs: '% (module_name, test_name, str(qa_job_ids_str)))
        elif (len(abis) == 2) and (failures.get(abis[0]) != failures.get(abis[1])):
            for abi in abis:
                stacktrace_msg = '%s\n\n%s:\n%s' % (stacktrace_msg, abi, failures.get(abi))
        else:
            stacktrace_msg = failures.get(abis[0])

        if test_name.find(module_name) >=0:
            form_initial['summary'] = '%s: %s failed' % (project.get('name'), test_name.replace('#arm64-v8a', '').replace('#armeabi-v7a', ''))
            description = '%s' % (test_name)
        else:
            form_initial['summary'] = '%s: %s %s failed' % (project.get('name'), module_name, test_name.replace('#arm64-v8a', '').replace('#armeabi-v7a', ''))
            description = '%s %s' % ( module_name, test_name.replace('#arm64-v8a', '').replace('#armeabi-v7a', ''))

        history_urls = []
        for abi in abis:
            if module_name.startswith('Vts'):
                test_res_dir = 'vts-test'
            else:
                test_res_dir = 'cts-lkft'
            history_url = '%s/%s/tests/%s/%s.%s/%s' % (qa_report_api.get_api_url_prefix(),
                                                             project.get('full_name'),
                                                             test_res_dir,
                                                             abi,
                                                             module_name,
                                                             test_name.replace('#arm64-v8a', '').replace('#armeabi-v7a', '').replace('#', '.'))
            history_urls.append(history_url)

        description += '\n\nABIs:\n%s' % (' '.join(abis))
        description += '\n\nQA Report Test History Urls:\n%s' % ('\n'.join(history_urls))
        description += '\n\nKernels:\n%s' % (' '.join(sorted(failed_kernels)))
        description += '\n\nBuild Version:\n%s' % (build.get('version'))
        description += '\n\nStackTrace: \n%s' % (stacktrace_msg.strip())
        description += '\n\nLava Jobs:'
        for qa_job in qa_jobs:
            description += '\n%s' % (qa_job.get('external_url'))

        description += '\n\nResult File Urls:'
        for qa_job in qa_jobs:
            description += '\n%s' % qa_job.get('attachment_url')

        #description += '\n\nImages Url:\n%s/%s/%s' % (android_snapshot_url_base, build_name, build_no)

        form_initial['description'] = description
        form = BugCreationForm(initial=form_initial)

        build_info = {
                      'build_name': 'build_name',
                      'build_no': 'build_no',
                     }
    return render(request, 'lkft-file-bug.html',
                    {
                        "form": form,
                        'build_info': build_info,
                    })


@login_required
@permission_required('lkft.admin_projects')
def resubmit_job(request):
    qa_job_ids = request.POST.getlist("qa_job_ids")
    if len(qa_job_ids) == 0:
        qa_job_id = request.GET.get("qa_job_id", "")
        if qa_job_id:
            qa_job_ids = [qa_job_id]

    if len(qa_job_ids) == 0:
        return render(request, 'lkft-job-resubmit.html',
                      {
                        'errors': True,
                      })
    logger.info('user: %s is going to resubmit job: %s' % (request.user, str(qa_job_ids)))

    qa_job = qa_report_api.get_job_with_id(qa_job_ids[0])
    build_url = qa_job.get('target_build')
    build_id = build_url.strip('/').split('/')[-1]

    jobs = get_jobs_for_build_from_db_or_qareport(build_id=build_id, force_fetch_from_qareport=True)
    parent_job_urls = []
    for job in jobs:
        parent_job_url = job.get('parent_job')
        if parent_job_url:
            parent_job_urls.append(parent_job_url.strip('/'))

    succeed_qa_job_urls = []
    failed_qa_jobs = {}
    old_job_urls = []
    for qa_job_id in qa_job_ids:
        qa_job_url = qa_report_api.get_job_api_url(qa_job_id).strip('/')
        old_job_urls.append(qa_job_url)

        if qa_job_url in parent_job_urls:
            continue

        res = qa_report_api.forceresubmit(qa_job_id)
        if res.ok:
            succeed_qa_job_urls.append(qa_job_url)
            qa_build =  qa_report_api.get_build(build_id)
            qa_project =  qa_report_api.get_project_with_url(qa_build.get('project'))

            try:
                db_reportproject = ReportProject.objects.get(project_id=qa_project.get('id'))
                db_report_build = ReportBuild.objects.get(version=qa_build.get('version'), qa_project=db_reportproject)
                db_report_build.status = 'JOBSINPROGRESS'
                db_report_build.save()

                if db_report_build.kernel_change:
                    db_report_build.kernel_change.reported = False
                    db_report_build.kernel_change.save()

            except ReportProject.DoesNotExist:
                logger.info("db_reportproject not found for project_id=%s" % qa_project.get('id'))
                pass
            except ReportBuild.DoesNotExist:
                logger.info("db_report_build not found for project_id=%s, version=%s" % (qa_project.get('id'), qa_build.get('version')))
                pass
        else:
            failed_qa_jobs[qa_job_url] = res

    # assuming all the jobs are belong to the same build

    jobs = get_jobs_for_build_from_db_or_qareport(build_id=build_id, force_fetch_from_qareport=True)
    old_jobs = {}
    created_jobs = {}
    for job in jobs:
        qa_job_url = job.get('url').strip('/')
        if qa_job_url in old_job_urls:
            old_jobs[qa_job_url] = job

        parent_job_url = job.get('parent_job')
        if parent_job_url and parent_job_url.strip('/') in succeed_qa_job_urls:
            created_jobs[parent_job_url.strip('/')] = job


    results = []
    for qa_job_id in qa_job_ids:
        qa_job_url = qa_report_api.get_job_api_url(qa_job_id).strip('/')
        old = old_jobs.get(qa_job_url)
        if not old:
            results.append({
                'qa_job_url': qa_job_url,
                'old': None,
                'new': None,
                'error_msg': 'The job does not exists on qa-report'
            })
            continue

        if qa_job_url in parent_job_urls:
            results.append({
                'qa_job_url': qa_job_url,
                'old': old,
                'new': None,
                'error_msg': 'The job is a parent job, could not be resubmitted again'
            })
            continue

        new = created_jobs.get(qa_job_url)
        if new:
            results.append({
                'qa_job_url': qa_job_url,
                'old': old,
                'new': new,
                'error_msg': None
                })
            continue

        response = failed_qa_jobs.get(qa_job_url)
        if response is not None:
            results.append({
                'qa_job_url': qa_job_url,
                'old': old,
                'new': new,
                'error_msg': 'Reason: %s<br/>Status Code: %s<br/>Url: %s' % (response.reason, response.status_code, response.url)
            })
        else:
            results.append({
                'qa_job_url': qa_job_url,
                'old': old,
                'new': new,
                'error_msg': 'Unknown Error happend, No job has the original job as parent, and no response found'
            })

    return render(request, 'lkft-job-resubmit.html',
                  {
                   'results': results,
                  }
    )


@login_required
@permission_required('lkft.admin_projects')
def cancel_job(request, qa_job_id):
    qa_job = qa_report_api.get_job_with_id(qa_job_id)
    if qa_job.get('job_status') == 'Submitted' \
            or qa_job.get('job_status') == 'Running':
        lava_config = find_lava_config(qa_job.get('external_url'))
        if not lava_config:
            logger.error('lava server is not found for job: %s' % job.get('url'))
        else:
            res = qa_report.LAVAApi(lava_config=lava_config).cancel_job(lava_job_id=qa_job.get('job_id'))
            logger.info("Tried to canncel job with res.status_code=%s: %s" % (res.status_code, qa_job.get('external_url')))
    return redirect(qa_job.get('external_url'))


@login_required
@permission_required('lkft.admin_projects')
def cancel_build(request, qa_build_id):
    qa_jobs = get_jobs_for_build_from_db_or_qareport(build_id=qa_build_id, force_fetch_from_qareport=True)
    for qa_job in qa_jobs:
        if qa_job.get('job_status') != 'Submitted' \
                and qa_job.get('job_status') != 'Running':
            continue

        if qa_job.get('external_url') is None:
            continue

        lava_config = find_lava_config(qa_job.get('external_url'))
        if not lava_config:
            continue

        res = qa_report.LAVAApi(lava_config=lava_config).cancel_job(lava_job_id=qa_job.get('job_id'))
        logger.info("Tried to canncel job with res.status_code=%s: %s" % (res.status_code, qa_job.get('external_url')))
    return redirect("/lkft/jobs/?build_id={}".format(qa_build_id))


def new_kernel_changes(request, branch, describe, trigger_name, trigger_number):

    supported_branches = get_supported_branches()
    if branch not in supported_branches:
        return HttpResponse("ERROR: branch %s is not supported yet" % branch, status=200)

    remote_addr = request.META.get("REMOTE_ADDR")
    remote_host = request.META.get("REMOTE_HOST")
    logger.info('request from remote_host=%s,remote_addr=%s' % (remote_host, remote_addr))
    logger.info('request for branch=%s, describe=%s, trigger_name=%s, trigger_number=%s' % (branch, describe, trigger_name, trigger_number))

    err_msg = None
    db_kernelchange, newly_created = KernelChange.objects.get_or_create(branch=branch, describe=describe)
    if not newly_created:
        err_msg = 'request for branch=%s, describe=%s is already there' % (branch, describe)
        logger.info(err_msg)
    else:
        db_kernelchange.trigger_name = trigger_name
        db_kernelchange.trigger_number = trigger_number
        db_kernelchange.save()

        db_cibuild, newly_created = CiBuild.objects.get_or_create(name=trigger_name, number=trigger_number)
        if db_cibuild.kernel_change is None:
            db_cibuild.kernel_change = db_kernelchange
            db_cibuild.save()

        irc.sendAndQuit(msgStrOrAry="New kernel changes found: branch=%s, describe=%s, %s" % (branch, describe, "https://ci.linaro.org/job/%s/%s" % (trigger_name, trigger_number)))

    if err_msg is not None:
        return HttpResponse("ERROR:%s" % err_msg,
                            status=200)

    return HttpResponse(status=200)


def new_build(request, branch, describe, name, number):

    supported_branches = get_supported_branches()
    if branch not in supported_branches:
        return HttpResponse("ERROR: branch %s is not supported yet" % branch, status=200)

    remote_addr = request.META.get("REMOTE_ADDR")
    remote_host = request.META.get("REMOTE_HOST")
    logger.info('request from %s %s' % (remote_host, remote_addr))
    logger.info('request for branch=%s, describe=%s, trigger_name=%s, trigger_number=%s' % (branch, describe, name, number))

    err_msg = None

    db_kernelchange, kernelchange_newly_created = KernelChange.objects.get_or_create(branch=branch, describe=describe)
    if kernelchange_newly_created:
        err_msg = "The change for the specified kernel and describe does not exist but created: branch=%s, describe=%s" % (branch, describe)

    db_cibuild, cibuild_newly_created = CiBuild.objects.get_or_create(name=name, number=number)
    if not cibuild_newly_created:
        if err_msg is not None:
            err_msg = "%s, and the build already recorded: name=%s, number=%s" % (err_msg, name, number)
        else:
            err_msg = "The build already recorded: name=%s, number=%s" % (name, number)
    else:
        # the build is resubmitted
        db_kernelchange.reported = False
        db_kernelchange.save()

    if db_cibuild.kernel_change is None:
        db_cibuild.kernel_change = db_kernelchange
        db_cibuild.save()

    if db_kernelchange.trigger_name is None or db_kernelchange.trigger_number is None:
        ci_build_url = jenkins_api.get_job_url(name=name, number=number)
        ci_build = jenkins_api.get_build_details_with_full_url(build_url=ci_build_url)
        trigger_ci_build = jenkins_api.get_final_trigger_from_ci_build(ci_build)
        trigger_ci_build_url = trigger_ci_build.get('url')
        trigger_ci_build_number = trigger_ci_build_url.strip('/').split('/')[-1]
        trigger_ci_build_name = trigger_ci_build_url.strip('/').split('/')[-2]
        db_kernelchange.trigger_name = trigger_ci_build_name
        db_kernelchange.trigger_number = trigger_ci_build_number
        db_kernelchange.save()

    if err_msg is None:
        return HttpResponse(status=200)
    else:
        logger.info(err_msg)
        return HttpResponse("ERROR:%s" % err_msg,
                            status=200)


def get_ci_build_info(build_name, build_number):
    ci_build_url = jenkins_api.get_job_url(name=build_name, number=build_number)
    try:
        ci_build = jenkins_api.get_build_details_with_full_url(build_url=ci_build_url)
        ci_build['start_timestamp'] = qa_report_api.get_aware_datetime_from_timestamp(int(ci_build['timestamp'])/1000)
        kernel_change_start_timestamp = ci_build['start_timestamp']

        if ci_build.get('building'):
            ci_build['status'] = 'INPROGRESS'
            ci_build['duration'] = datetime.timedelta(milliseconds=0)
        else:
            ci_build['status']  = ci_build.get('result') # null or SUCCESS, FAILURE, ABORTED
            ci_build['duration'] = datetime.timedelta(milliseconds=ci_build['duration'])
        ci_build['finished_timestamp'] = ci_build['start_timestamp'] + ci_build['duration']

    except qa_report.UrlNotFoundException as e:
        ci_build = {
                'number': build_number,
                'status': 'CI_BUILD_DELETED',
                'duration': datetime.timedelta(milliseconds=0),
                'actions': [],
            }

    ci_build['name'] = build_name
    return ci_build


def get_qareport_build(build_version, qaproject_name, cached_qaprojects=[], cached_qareport_builds=[]):
    target_qareport_project = None
    for lkft_project in cached_qaprojects:
        if lkft_project.get('full_name') == qaproject_name:
            target_qareport_project = lkft_project
            break
    if target_qareport_project is None:
        return (None, None)

    target_qareport_project_id = target_qareport_project.get('id')
    builds = cached_qareport_builds.get(target_qareport_project_id)
    if builds is None:
        builds = qa_report_api.get_all_builds(target_qareport_project_id)
        cached_qareport_builds[target_qareport_project_id] = builds

    target_qareport_build = None
    for build in builds:
        if build.get('version') == build_version:
            target_qareport_build = build
            break

    return (target_qareport_project, target_qareport_build)


def get_kernel_changes_info(db_kernelchanges=[]):
    number_kernelchanges = len(db_kernelchanges)
    if number_kernelchanges < 1:
        return []

    queued_ci_items = jenkins_api.get_queued_items()
    lkft_projects = qa_report_api.get_lkft_qa_report_projects(include_archived=True)
    kernelchanges = []
    # add the same project might have several kernel changes not finished yet
    project_builds = {} # cache builds for the project

    index = 0
    logger.info("length of kernel changes: %s" % number_kernelchanges)
    for db_kernelchange in db_kernelchanges:
        index = index +1
        logger.info("%d/%d: Try to get info for kernel change: %s %s %s %s" % (index, number_kernelchanges, db_kernelchange.branch, db_kernelchange.describe, db_kernelchange.result, timesince(db_kernelchange.timestamp)))
        test_numbers = qa_report.TestNumbers()
        kernelchange = {}
        if db_kernelchange.reported and db_kernelchange.result == 'ALL_COMPLETED':
            kernelchange = { 'kernel_change': db_kernelchange }
            kernelchanges.append(kernelchange)
            continue

        trigger_build = get_ci_build_info(db_kernelchange.trigger_name, db_kernelchange.trigger_number)
        trigger_build['kernel_change'] = db_kernelchange
        if trigger_build.get('start_timestamp') is None:
            trigger_build['start_timestamp'] = db_kernelchange.timestamp
            trigger_build['finished_timestamp'] = trigger_build['start_timestamp'] + trigger_build['duration']
            kernel_change_status = "TRIGGER_BUILD_DELETED"
        else:
            kernel_change_status = "TRIGGER_BUILD_COMPLETED"
        kernel_change_finished_timestamp = trigger_build['finished_timestamp']

        dbci_builds = CiBuild.objects_kernel_change.get_builds_per_kernel_change(kernel_change=db_kernelchange).order_by('name', '-number')
        expect_build_names = find_expect_cibuilds(trigger_name=db_kernelchange.trigger_name, branch_name=db_kernelchange.branch)

        # used to cached all the ci builds data
        jenkins_ci_builds = []
        # used to record the lkft build config to find the qa-report project
        lkft_build_configs = {}
        ci_build_names = []
        has_build_inprogress = False
        # success, inprogress, inqueue jobs are not failed jobs
        all_builds_failed = True
        all_builds_has_failed = False
        for dbci_build in dbci_builds:
            #if dbci_build.name == db_kernelchange.trigger_name:
            #    # ignore the trigger builds
            #    continue
            #else:
            ci_build_names.append(dbci_build.name)

            build = get_ci_build_info(dbci_build.name, dbci_build.number)
            build['dbci_build'] = dbci_build
            jenkins_ci_builds.append(build)
            if build.get('status') == 'INPROGRESS':
                has_build_inprogress = True
                all_builds_failed = False

            if build.get('status') != 'SUCCESS':
                # no need to check the build/job results as the ci build not finished successfully yet
                # and the qa-report build is not created yet
                all_builds_has_failed = True
                continue
            elif dbci_build.name != db_kernelchange.trigger_name:
                # not the trigger build, and the ci build finished successfully
                all_builds_failed = False

            str_configs = jenkins_api.get_build_configs(build)
            if str_configs:
                for lkft_build_config in str_configs.split():
                    if lkft_build_config.startswith('lkft-gki-'):
                        # gki builds does not have any qa-preoject set
                        continue
                    if lkft_build_configs.get(lkft_build_config) is not None:
                        # only use the latest build(which might be triggered manually) for the same kernel change
                        # even for the generic build that used the same lkft_build_config.
                        # used the "-number" filter to make sure ci builds is sorted in descending,
                        # and the first one is the latest
                        continue
                    lkft_build_configs[lkft_build_config] = build

        not_started_ci_builds = expect_build_names - set(ci_build_names)

        # need to check how to find the builds not started or failed
        queued_ci_builds = []
        disabled_ci_builds = []
        not_reported_ci_builds = []
        if len(not_started_ci_builds) > 0:
            for cibuild_name in not_started_ci_builds:
                is_queued_build = False
                for queued_item in queued_ci_items:
                    if cibuild_name == queued_item.get('build_name') and \
                        db_kernelchange.describe == queued_item.get('KERNEL_DESCRIBE'):
                            is_queued_build = True
                            queued_ci_builds.append(queued_item)
                if is_queued_build:
                    continue

                if jenkins_api.is_build_disabled(cibuild_name):
                    disabled_ci_builds.append(cibuild_name)
                #else:
                #    not_reported_ci_builds.append(cibuild_name)

        if queued_ci_builds:
            kernel_change_status = "CI_BUILDS_IN_QUEUE"
        elif has_build_inprogress:
            kernel_change_status = "CI_BUILDS_IN_PROGRESS"
        elif not_reported_ci_builds:
            kernel_change_status = "CI_BUILDS_NOT_REPORTED"
            logger.info("NOT REPORTED BUILDS: %s" % ' '.join(not_reported_ci_builds))
        elif all_builds_failed:
            kernel_change_status = "CI_BUILDS_ALL_FAILED"
        elif all_builds_has_failed:
            kernel_change_status = "CI_BUILDS_HAS_FAILED"
        else:
            kernel_change_status = "CI_BUILDS_COMPLETED" # might be the case that some failed, some passed

        qa_report_builds = []
        has_jobs_not_submitted = False
        has_jobs_canceled = False
        has_jobs_in_progress = False
        all_jobs_finished = False

        qareport_project_not_found_configs = []
        qareport_build_not_found_configs = []
        for lkft_build_config, ci_build in lkft_build_configs.items():
            override_plans = jenkins_api.get_override_plans(ci_build)
            projects = get_qa_server_project(lkft_build_config_name=lkft_build_config, override_plans=override_plans)
            for (project_group, project_name) in projects:
                target_lkft_project_full_name = "%s/%s" % (project_group, project_name)
                (target_qareport_project, target_qareport_build) = get_qareport_build(db_kernelchange.describe,
                                                                        target_lkft_project_full_name,
                                                                        cached_qaprojects=lkft_projects,
                                                                        cached_qareport_builds=project_builds)
                if target_qareport_project is None:
                    logger.info("target_qareport_project is not found for project:{}, for build config:{}".format(target_lkft_project_full_name, lkft_build_config))
                    qareport_project_not_found_configs.append(lkft_build_config)
                    continue

                if target_qareport_build is None:
                    logger.info("target_qareport_build is not found for project:{}, for build config:{}".format(target_lkft_project_full_name, lkft_build_config))
                    qareport_build_not_found_configs.append(lkft_build_config)
                    continue

                created_str = target_qareport_build.get('created_at')
                target_qareport_build['created_at'] = qa_report_api.get_aware_datetime_from_str(created_str)
                target_qareport_build['project_name'] = project_name
                target_qareport_build['project_group'] = project_group
                target_qareport_build['project_slug'] = target_qareport_project.get('slug')
                target_qareport_build['project_id'] = target_qareport_project.get('id')

                jobs = get_jobs_for_build_from_db_or_qareport(build_id=target_qareport_build.get("id"), force_fetch_from_qareport=True)
                classified_jobs = get_classified_jobs(jobs=jobs)
                final_jobs = classified_jobs.get('final_jobs')
                resubmitted_or_duplicated_jobs = classified_jobs.get('resubmitted_or_duplicated_jobs')

                build_status = get_lkft_build_status(target_qareport_build, final_jobs)
                if build_status['has_unsubmitted']:
                    has_jobs_not_submitted = True
                elif build_status['is_inprogress']:
                    has_jobs_in_progress = True
                elif build_status['has_canceled']:
                    has_jobs_canceled = True
                else:
                    if kernel_change_finished_timestamp is None or \
                        kernel_change_finished_timestamp < build_status['last_fetched_timestamp']:
                        kernel_change_finished_timestamp = build_status['last_fetched_timestamp']
                    target_qareport_build['duration'] = build_status['last_fetched_timestamp'] - target_qareport_build['created_at']

                numbers_of_result = get_test_result_number_for_build(target_qareport_build, final_jobs)
                target_qareport_build['numbers_of_result'] = numbers_of_result
                target_qareport_build['qa_report_project'] = target_qareport_project
                target_qareport_build['final_jobs'] = final_jobs
                target_qareport_build['resubmitted_or_duplicated_jobs'] = resubmitted_or_duplicated_jobs
                target_qareport_build['ci_build'] = ci_build

                qa_report_builds.append(target_qareport_build)
                test_numbers.addWithHash(numbers_of_result)

        has_error = False
        error_dict = {}
        if kernel_change_status == "CI_BUILDS_COMPLETED":
            if len(lkft_build_configs) == 0:
                kernel_change_status = 'NO_QA_PROJECT_FOUND'
            elif qareport_project_not_found_configs or qareport_build_not_found_configs:
                has_error = True
                if qareport_project_not_found_configs:
                    kernel_change_status = 'HAS_QA_PROJECT_NOT_FOUND'
                    error_dict['qareport_project_not_found_configs'] = qareport_project_not_found_configs
                    logger.info("qareport_build_not_found_configs: %s" % ' '.join(qareport_build_not_found_configs))
                if qareport_build_not_found_configs:
                    kernel_change_status = 'HAS_QA_BUILD_NOT_FOUND'
                    error_dict['qareport_build_not_found_configs'] = qareport_build_not_found_configs
                    logger.info("qareport_build_not_found_configs: %s" % ' '.join(qareport_build_not_found_configs))
            elif has_jobs_not_submitted:
                kernel_change_status = 'HAS_JOBS_NOT_SUBMITTED'
            elif has_jobs_in_progress:
                kernel_change_status = 'HAS_JOBS_IN_PROGRESS'
            elif has_jobs_canceled:
                kernel_change_status = 'HAS_JOBS_CANCELED'
            else:
                kernel_change_status = 'ALL_COMPLETED'

        kernelchange = {
                'kernel_change': db_kernelchange,
                'trigger_build': trigger_build,
                'jenkins_ci_builds': jenkins_ci_builds,
                'qa_report_builds': qa_report_builds,
                'kernel_change_status': kernel_change_status,
                'error_dict': error_dict,
                'queued_ci_builds': queued_ci_builds,
                'disabled_ci_builds': disabled_ci_builds,
                'not_reported_ci_builds': not_reported_ci_builds,
                'start_timestamp': trigger_build.get('start_timestamp'),
                'finished_timestamp': kernel_change_finished_timestamp,
                'test_numbers': test_numbers,
            }

        kernelchanges.append(kernelchange)

    return kernelchanges


def get_kernel_changes_info_wrapper_for_display(db_kernelchanges=[]):
    kernelchanges = get_kernel_changes_info(db_kernelchanges=db_kernelchanges)
    kernelchanges_return = []
    for kernelchange in kernelchanges:
        kernelchange_return = {}
        db_kernelchange = kernelchange.get('kernel_change')

        kernelchange_return['branch'] = db_kernelchange.branch
        kernelchange_return['describe'] = db_kernelchange.describe
        kernelchange_return['trigger_name'] = db_kernelchange.trigger_name
        kernelchange_return['trigger_number'] = db_kernelchange.trigger_number

        if db_kernelchange.reported and db_kernelchange.result == 'ALL_COMPLETED':
            kernelchange_return['start_timestamp'] = db_kernelchange.timestamp
            kernelchange_return['finished_timestamp'] = None
            kernelchange_return['duration'] = datetime.timedelta(seconds=db_kernelchange.duration)
            kernelchange_return['status'] = db_kernelchange.result
            kernelchange_return['number_passed'] = db_kernelchange.number_passed
            kernelchange_return['number_failed'] = db_kernelchange.number_failed
            kernelchange_return['number_assumption_failure'] = db_kernelchange.number_assumption_failure
            kernelchange_return['number_ignored'] = db_kernelchange.number_ignored
            kernelchange_return['number_total'] = db_kernelchange.number_total
            kernelchange_return['modules_done'] = db_kernelchange.modules_done
            kernelchange_return['modules_total'] = db_kernelchange.modules_total
            kernelchange_return['jobs_finished'] = db_kernelchange.jobs_finished
            kernelchange_return['jobs_total'] = db_kernelchange.jobs_total
        else:
            test_numbers = kernelchange.get('test_numbers')
            kernelchange_return['start_timestamp'] = kernelchange.get('start_timestamp')
            kernelchange_return['finished_timestamp'] = kernelchange.get('finished_timestamp')
            kernelchange_return['duration'] = kernelchange_return['finished_timestamp'] - kernelchange_return['start_timestamp']

            kernelchange_return['status'] = kernelchange.get('kernel_change_status')

            kernelchange_return['number_passed'] = test_numbers.number_passed
            kernelchange_return['number_failed'] = test_numbers.number_failed
            kernelchange_return['number_assumption_failure'] = test_numbers.number_assumption_failure
            kernelchange_return['number_ignored'] = test_numbers.number_ignored
            kernelchange_return['number_total'] = test_numbers.number_total
            kernelchange_return['modules_done'] = test_numbers.modules_done
            kernelchange_return['modules_total'] = test_numbers.modules_total
            kernelchange_return['jobs_finished'] = test_numbers.jobs_finished
            kernelchange_return['jobs_total'] = test_numbers.jobs_total

        kernelchanges_return.append(kernelchange_return)

    return kernelchanges_return


def get_kernel_changes_for_all_branches():
    db_kernelchanges = KernelChange.objects.all().order_by('branch', '-trigger_number')
    check_branches = []
    unique_branch_names = []
    for db_kernelchange in db_kernelchanges:
        if db_kernelchange.branch in unique_branch_names:
            continue
        else:
            unique_branch_names.append(db_kernelchange.branch)
            check_branches.append(db_kernelchange)

    return get_kernel_changes_info_wrapper_for_display(db_kernelchanges=check_branches)


@login_required
@permission_required('lkft.admin_projects')
def list_kernel_changes(request):
    kernelchanges = get_kernel_changes_for_all_branches()
    return render(request, 'lkft-kernelchanges.html',
                       {
                            "kernelchanges": kernelchanges,
                        }
            )

@login_required
@permission_required('lkft.admin_projects')
def list_branch_kernel_changes(request, branch):
    db_kernelchanges = KernelChange.objects.all().filter(branch=branch).order_by('-trigger_number')
    kernelchanges = get_kernel_changes_info_wrapper_for_display(db_kernelchanges=db_kernelchanges)

    return render(request, 'lkft-kernelchanges.html',
                       {
                            "kernelchanges": kernelchanges,
                        }
            )
@login_required
@permission_required('lkft.admin_projects')
def list_describe_kernel_changes(request, branch, describe):
    db_kernel_change = KernelChange.objects.get(branch=branch, describe=describe)
    db_report_builds = ReportBuild.objects.filter(kernel_change=db_kernel_change).order_by('qa_project__group', 'qa_project__name')
    db_ci_builds = CiBuild.objects.filter(kernel_change=db_kernel_change).exclude(name=db_kernel_change.trigger_name).order_by('name', 'number')
    db_trigger_build = CiBuild.objects.get(name=db_kernel_change.trigger_name, kernel_change=db_kernel_change)

    kernel_change = {}
    kernel_change['branch'] = db_kernel_change.branch
    kernel_change['describe'] = db_kernel_change.describe
    kernel_change['result'] = db_kernel_change.result
    kernel_change['trigger_name'] = db_kernel_change.trigger_name
    kernel_change['trigger_number'] = db_kernel_change.trigger_number
    kernel_change['timestamp'] = db_kernel_change.timestamp
    kernel_change['duration'] = datetime.timedelta(seconds=db_kernel_change.duration)
    kernel_change['number_passed'] = db_kernel_change.number_passed
    kernel_change['number_failed'] = db_kernel_change.number_failed
    kernel_change['number_assumption_failure'] = db_kernel_change.number_assumption_failure
    kernel_change['number_ignored'] = db_kernel_change.number_ignored
    kernel_change['number_total'] = db_kernel_change.number_total
    kernel_change['modules_done'] = db_kernel_change.modules_done
    kernel_change['modules_total'] = db_kernel_change.modules_total
    kernel_change['jobs_finished'] = db_kernel_change.jobs_finished
    kernel_change['jobs_total'] = db_kernel_change.jobs_total
    kernel_change['reported'] = db_kernel_change.reported

    trigger_build = {}
    trigger_build['name'] = db_trigger_build.name
    trigger_build['number'] = db_trigger_build.number
    trigger_build['timestamp'] = db_trigger_build.timestamp
    trigger_build['result'] = db_trigger_build.result
    trigger_build['duration'] = datetime.timedelta(seconds=db_trigger_build.duration)

    ci_builds = []
    for db_ci_build in db_ci_builds:
        ci_build = {}
        ci_build['name'] = db_ci_build.name
        ci_build['number'] = db_ci_build.number
        ci_build['timestamp'] = db_ci_build.timestamp
        ci_build['result'] = db_ci_build.result
        ci_build['duration'] = datetime.timedelta(seconds=db_ci_build.duration)
        if db_ci_build.timestamp and db_trigger_build.timestamp:
            ci_build['queued_duration'] = db_ci_build.timestamp - db_trigger_build.timestamp  - trigger_build['duration']
        ci_builds.append(ci_build)

    report_builds = []
    db_report_jobs = []
    for db_report_build in db_report_builds:
        report_build = {}
        report_build['qa_project'] = db_report_build.qa_project
        report_build['started_at'] = db_report_build.started_at
        report_build['number_passed'] = db_report_build.number_passed
        report_build['number_failed'] = db_report_build.number_failed
        report_build['number_assumption_failure'] = db_report_build.number_assumption_failure
        report_build['number_ignored'] = db_report_build.number_ignored
        report_build['number_total'] = db_report_build.number_total
        report_build['modules_done'] = db_report_build.modules_done
        report_build['modules_total'] = db_report_build.modules_total
        report_build['jobs_finished'] = db_report_build.jobs_finished
        report_build['jobs_total'] = db_report_build.jobs_total
        report_build['qa_build_id'] = db_report_build.qa_build_id
        report_build['status'] = db_report_build.status
        if db_report_build.fetched_at and db_report_build.started_at:
            report_build['duration'] = db_report_build.fetched_at - db_report_build.started_at

        report_builds.append(report_build)

        db_report_jobs_of_build = ReportJob.objects.filter(report_build=db_report_build)
        db_report_jobs.extend(db_report_jobs_of_build)

    report_jobs = []
    resubmitted_jobs = []
    for db_report_job in db_report_jobs:
        report_job = {}
        db_report_build = db_report_job.report_build
        db_report_project = db_report_build.qa_project
        report_job['qaproject_full_name'] = "%s/%s" % (db_report_project.group, db_report_project.name)
        report_job['qaproject_group'] = db_report_project.group
        report_job['qaproject_name'] = db_report_project.name
        report_job['qaproject_url'] = qa_report_api.get_project_url_with_group_slug(db_report_project.group, db_report_project.slug)
        report_job['qabuild_version'] = db_report_build.version
        report_job['qajob_id'] = db_report_job.qa_job_id
        report_job['qabuild_url'] = qa_report_api.get_build_url_with_group_slug_buildVersion(db_report_project.group,
                                                                                             db_report_project.slug,
                                                                                             db_report_build.version)

        report_job['lavajob_id'] = qa_report_api.get_qa_job_id_with_url(db_report_job.job_url)
        report_job['lavajob_url'] = db_report_job.job_url
        report_job['lavajob_name'] = db_report_job.job_name
        report_job['lavajob_attachment_url'] = db_report_job.attachment_url
        report_job['lavajob_status'] = db_report_job.status
        report_job['failure_msg'] = db_report_job.failure_msg

        report_job['number_passed'] = db_report_job.number_passed
        report_job['number_failed'] = db_report_job.number_failed
        report_job['number_assumption_failure'] = db_report_job.number_assumption_failure
        report_job['number_ignored'] = db_report_job.number_ignored
        report_job['number_total'] = db_report_job.number_total
        report_job['modules_done'] = db_report_job.modules_done
        report_job['modules_total'] = db_report_job.modules_total

        if db_report_job.resubmitted:
            resubmitted_jobs.append(report_job)
        else:
            report_jobs.append(report_job)

    return render(request, 'lkft-describe.html',
                       {
                            "kernel_change": kernel_change,
                            'report_builds': report_builds,
                            'trigger_build': trigger_build,
                            'ci_builds': ci_builds,
                            'report_jobs': report_jobs,
                            'resubmitted_jobs': resubmitted_jobs,
                        }
            )


@login_required
@permission_required('lkft.admin_projects')
def mark_kernel_changes_reported(request, branch, describe):
    db_kernel_change = KernelChange.objects.get(branch=branch, describe=describe)
    db_kernel_change.reported = (not db_kernel_change.reported)
    db_kernel_change.save()
    return redirect("/lkft/kernel-changes/{}/{}/".format(branch, describe))


def homepage(request):
    return render(request, 'lkft-homepage.html')

def list_projects_simple(request):

    fetch_latest_from_qa_report = request.GET.get('fetch_latest', "false").lower() == 'true'

    groups = [
            {
                'group_id': '42',
                'group_name': 'android-lkft-benchmarks',
                'display_title': "Boottime Projects",
            },
            {
                'group_id': '17',
                'group_name': 'android-lkft',
                'display_title': "LKFT Projects",
            },
            # {
            #     'group_name': 'android-lkft-rc',
            #     'display_title': "RC Projects",
            # },
        ]

    for group in groups:
        group_id = group.get('group_id')
        group_name = group.get('group_name')


        logger.info('start to get the projects for group %s' %  group.get('group_name'))
        projects = []
        if fetch_latest_from_qa_report:
            projects = qa_report_api.get_projects_with_group_id(group_id)
            for target_project in projects:
                cache_qaproject_to_database(target_project)
        else:
            db_report_projects = ReportProject.objects.filter(group=group_name)
            for db_project in db_report_projects:
                project = {
                            'full_name': qa_report_api.get_project_full_name_with_group_and_slug(group_name, db_project.slug),
                            'name': db_project.name,
                            'slug': db_project.slug,
                            'id': db_project.project_id,
                            'is_public': db_project.is_public,
                            'is_archived': db_project.is_archived,
                            }
                projects.append(project)

        logger.info('end to get the projects for group %s' %  group.get('group_name'))
        for project in projects:
            if project.get('is_archived'):
                continue

            if not is_project_accessible(project_full_name=project.get('full_name'), user=request.user):
                # the current user has no permission to access the project
                continue

            project['group'] = group

            group_projects = group.get('projects')
            if group_projects:
                group_projects.append(project)
            else:
                group['projects'] = [project]
                group['qareport_url'] = project.get('group')



    def get_project_name(item):
        #4.19q
        versions = item.get('name').split('-')[0].split('.')
        try:
            version_0 = int(versions[0])

            if versions[1].endswith('o'):
                version_1 = int(versions[1].strip('o'))
                version_2 = "o"
            elif versions[1].endswith('p'):
                version_1 = int(versions[1].strip('p'))
                version_2 = "p"
            elif versions[1].endswith('q'):
                version_1 = int(versions[1].strip('q'))
                version_2 = "q"
            else:
                version_1 = int(versions[1])
                version_2 = ""
        except ValueError:
            version_0 = 256
            version_1 = ""
            version_2 = ""

        return (version_0, version_1, version_2)

    for group in groups:
        if group.get('projects'):
            sorted_projects = sorted(group['projects'], key=get_project_name, reverse=True)
            group['projects'] = sorted_projects
        else:
            group['projects'] = []


    title_head = "LKFT Projects"
    response_data = {
        'title_head': title_head,
        'groups': groups,
        'fetch_latest': fetch_latest_from_qa_report,
    }

    return render(request, 'lkft-projects-simple.html', response_data)

########################################
### Register for IRC functions
########################################
def func_irc_list_kernel_changes(irc=None, text=None):
    if irc is None:
        return
    kernelchanges = get_kernel_changes_for_all_branches()
    ircMsgs = []
    for kernelchange in kernelchanges:
        irc_msg = "branch:%s, describe=%s, %s, modules_done=%s" % (kernelchange.get('branch'),
                        kernelchange.get('describe'),
                        kernelchange.get('status'),
                        kernelchange.get('modules_done'))
        ircMsgs.append(irc_msg)

    irc.send(ircMsgs)

irc_notify_funcs = {
    'listkernelchanges': func_irc_list_kernel_changes,
}

irc.addFunctions(irc_notify_funcs)

########################################
########################################
