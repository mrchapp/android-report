# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.utils import timezone

from django.db import models

class KernelChangeManager(models.Manager):
    def get_queryset(self):
        return super(KernelChangeManager, self).get_queryset().filter(reported=False)

class KernelChange(models.Model):
    branch = models.CharField(max_length=255)
    describe = models.CharField(max_length=255)
    reported = models.BooleanField()
    trigger_name = models.CharField(max_length=255)
    trigger_number = models.IntegerField()

    # TRIGGER_BUILD_COMPLETED
    # CI_BUILDS_IN_QUEUE / CI_BUILDS_NOT_REPORTED / CI_BUILDS_IN_PROGRESS / CI_BUILDS_COMPLETED
    # HAS_QA_PROJECT_NOT_FOUND / HAS_QA_BUILD_NOT_FOUND / HAS_JOBS_NOT_SUBMITTED / HAS_JOBS_IN_PROGRESS
    # ALL_COMPLETED
    result = models.CharField(max_length=100, null=True, default="NOINFO")
    timestamp = models.DateTimeField(null=True, default=timezone.now)
    duration = models.IntegerField(default=0) # total_seconds

    number_passed = models.IntegerField(default=0)
    number_failed = models.IntegerField(default=0)
    number_assumption_failure = models.IntegerField(default=0)
    number_ignored = models.IntegerField(default=0)
    number_total = models.IntegerField(default=0)
    modules_done = models.IntegerField(default=0)
    modules_total = models.IntegerField(default=0)
    jobs_finished = models.IntegerField(default=0)
    jobs_total = models.IntegerField(default=0)


    def __str__(self):
        return "%s-%s" % (self.branch, self.describe)

    def __unicode__(self):
        return "%s-%s" % (self.branch, self.describe)

    objects = models.Manager() # The default manager
    objects_needs_report = KernelChangeManager() # custom managerKernelChangeManager()


class CiBuildKernelChangeManager(models.Manager):
    def get_builds_per_kernel_change(self, kernel_change=None):
        return super(CiBuildKernelChangeManager, self).get_queryset().filter(kernel_change=kernel_change)


class CiBuild(models.Model):
    name = models.CharField(max_length=255)
    number = models.IntegerField()
    kernel_change = models.ForeignKey(KernelChange, null=True, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(null=True, default=timezone.now)
    duration = models.IntegerField(default=0) # total_seconds
    # CI_BUILD_DELETED / INPROGRESS / SUCCESS / FAILURE / ABORTED
    result = models.CharField(max_length=100, null=True, default="NOINFO")

    def __str__(self):
        return "%s#%s" % (self.name, self.number)

    def __unicode__(self):
        return "%s#%s" % (self.name, self.number)

    objects = models.Manager()
    objects_kernel_change = CiBuildKernelChangeManager()


class ReportProject(models.Model):
    # the group that this build belongs to
    group = models.CharField(max_length=100)
    # the name of the qareport project
    name = models.CharField(max_length=100)
    # the slug of the qareport project
    slug = models.CharField(max_length=100)

    project_id = models.IntegerField(default=0)

    def __str__(self):
        return "%s#%s" % (self.group, self.name)

    def __unicode__(self):
        return "%s#%s" % (self.group, self.name)

    objects = models.Manager()


class ReportBuild(models.Model):
    # the version of the qareport build
    version = models.CharField(max_length=100)

    qa_project = models.ForeignKey(ReportProject, on_delete=models.CASCADE, null=True)
    kernel_change = models.ForeignKey(KernelChange, on_delete=models.CASCADE)
    ci_build = models.ForeignKey(CiBuild, on_delete=models.CASCADE, related_name="ci_build")
    ci_trigger_build = models.ForeignKey(CiBuild, on_delete=models.CASCADE, related_name='trigger_build')

    # JOBSNOTSUBMITTED / JOBSINPROGRESS / JOBSCOMPLETED
    status = models.CharField(max_length=100, null=True, default="NOINFO")

    number_passed = models.IntegerField(default=0)
    number_failed = models.IntegerField(default=0)
    number_assumption_failure = models.IntegerField(default=0)
    number_ignored = models.IntegerField(default=0)
    number_total = models.IntegerField(default=0)
    modules_done = models.IntegerField(default=0)
    modules_total = models.IntegerField(default=0)
    jobs_finished = models.IntegerField(default=0)
    jobs_total = models.IntegerField(default=0)

    # the time the trigger build was started
    started_at = models.DateTimeField(null=True)
    # the time the last job was fetched
    fetched_at = models.DateTimeField(null=True)

    # The id of the qa-report build id
    qa_build_id = models.IntegerField(default=0)

    def __str__(self):
        return "%s#%s" % (self.qa_project, self.version)

    def __unicode__(self):
        return "%s#%s" % (self.qa_project, self.version)

    objects = models.Manager()


class ReportJob(models.Model):
    job_name = models.CharField(max_length=100)
    job_url = models.URLField(null=True)
    attachment_url = models.URLField(null=True)
    results_cached = models.BooleanField(default=False)

    qa_job_id = models.IntegerField(default=0)

    report_build = models.ForeignKey(ReportBuild, on_delete=models.CASCADE, null=True)
    parent_job = models.CharField(max_length=100, null=True)
    resubmitted = models.BooleanField(default=False)

    # JOBSNOTSUBMITTED / JOBSINPROGRESS / JOBSCOMPLETED
    status = models.CharField(max_length=100, null=True, default="NOINFO")
    failure_msg = models.TextField(null=True, blank=True)

    submitted_at = models.DateTimeField(null=True)
    fetched_at = models.DateTimeField(null=True)

    number_passed = models.IntegerField(default=0)
    number_failed = models.IntegerField(default=0)
    number_assumption_failure = models.IntegerField(default=0)
    number_ignored = models.IntegerField(default=0)
    number_total = models.IntegerField(default=0)
    modules_done = models.IntegerField(default=0)
    modules_total = models.IntegerField(default=0)

    def __str__(self):
        if self.report_build:
            return "%s#%s" % (self.job_name, self.report_build.version)
        else:
            return "%s#%s" % (self.job_name, self.job_url)

    def __unicode__(self):
        if self.report_build:
            return "%s#%s" % (self.job_name, self.report_build.version)
        else:
            return "%s#%s" % (self.job_name, self.job_url)

    objects = models.Manager()


class TestSuite(models.Model):
    report_job = models.ForeignKey(ReportJob)

    name = models.CharField(max_length=256)
    abi = models.CharField(max_length=16, null=True)
    done = models.BooleanField(default=False)
    number_pass = models.IntegerField(default=0)
    number_total = models.IntegerField(default=0)


class TestCase(models.Model):
    name = models.CharField(max_length=256)
    result = models.CharField(max_length=64)
    measurement = models.DecimalField( max_digits=20, decimal_places=2, null=True)
    unit = models.CharField(max_length=128, null=True)
    suite = models.CharField(max_length=256)
    job_id = models.CharField(max_length=16)
    lava_nick = models.CharField(max_length=64)

    # failure should be deleted when this testcase deleted
    testsuite = models.ForeignKey(TestSuite, null=True)

    message = models.TextField(null=True, blank=True)
    stacktrace = models.TextField(null=True, blank=True)

    def __unicode__(self):
        if self.measurement:
            return "%s %s %s %s" % (self.name, self.result, self.measurement, self.unit)
        else:
            return "%s %s" % (self.name, self.result)
