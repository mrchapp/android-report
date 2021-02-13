# -*- coding: utf-8 -*-
# Generated by Django 1.11.17 on 2021-02-11 17:19
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lkft', '0014_auto_20210205_0641'),
    ]

    operations = [
        migrations.AddField(
            model_name='kernelchange',
            name='number_assumption_failure',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='kernelchange',
            name='number_ignored',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='reportbuild',
            name='number_assumption_failure',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='reportbuild',
            name='number_ignored',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='reportjob',
            name='number_assumption_failure',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='reportjob',
            name='number_ignored',
            field=models.IntegerField(default=0),
        ),
    ]
