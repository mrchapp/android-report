# https://docs.djangoproject.com/en/1.11/topics/db/managers/
# https://docs.djangoproject.com/en/dev/howto/custom-management-commands/#howto-custom-management-commands
# https://medium.com/@bencleary/django-scheduled-tasks-queues-part-1-62d6b6dc24f8
# https://medium.com/@bencleary/django-scheduled-tasks-queues-part-2-fc1fb810b81d
# https://medium.com/@kevin.michael.horan/scheduling-tasks-in-django-with-the-advanced-python-scheduler-663f17e868e6
# https://django-background-tasks.readthedocs.io/en/latest/


import datetime
import json
import logging
import os
import re
import yaml

from django.core.management.base import BaseCommand, CommandError

from lcr import qa_report

from lcr.settings import QA_REPORT, QA_REPORT_DEFAULT

from lkft.views import get_build_info

logger = logging.getLogger(__name__)

qa_report_def = QA_REPORT[QA_REPORT_DEFAULT]
qa_report_api = qa_report.QAReportApi(qa_report_def.get('domain'),
                                      qa_report_def.get('token'))


class Command(BaseCommand):
    help = 'Check the build and test results for kernel changes, \
            and send report if the jobs finished'

    def add_arguments(self, parser):
        parser.add_argument('project_fullname', type=str, nargs='?',
                            default=None)
        parser.add_argument("--project-group",
                            help="Specify the group for the project",
                            dest="project_group",
                            default="android-lkft",
                            required=False)
        parser.add_argument("--project-name",
                            help="Specify the name for the project",
                            dest="project_name",
                            default="5.4-gki-aosp-master-db845c-full-cts-vts",
                            required=False)
        parser.add_argument("--number-of-builds",
                            help="Specify the name for the project",
                            dest="number_of_builds",
                            type=int,
                            default=5,
                            required=False)

    def handle(self, *args, **options):
        option_pgroup = options.get('project_group')
        option_pname = options.get('project_name')
        option_pfullname = options['project_fullname']
        number_of_builds = options['number_of_builds']
        project_fullname = None
        if option_pfullname is not None:
            project_fullname = option_pfullname
        else:
            project_fullname = "{}/{}".format(option_pgroup, option_pname)

        project = qa_report_api.get_project_with_name(project_fullname)
        if project is None:
            print("No project with fullname of {} is found".format(
                    project_fullname))
        else:
            builds = qa_report_api.get_all_builds(project.get('id'))
            builds_result = []
            for build in builds[:number_of_builds]:
                builds_result.append(get_build_info(None, build))

            for build_result in builds_result:
                build_number = build.get('numbers')
                print("%s %d/%d/%d %d/%d" % (build.get("version"),
                                             build_number.get("number_passed"),
                                             build_number.get("number_failed"),
                                             build_number.get("number_total"),
                                             build_number.get("modules_done"),
                                             build_number.get("modules_total")
                                             ))
