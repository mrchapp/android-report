# -*- coding: utf-8 -*-
# Generated by Django 1.11.5 on 2017-10-09 11:10
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='TestCase',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128)),
                ('result', models.CharField(max_length=16)),
                ('measurement', models.DecimalField(decimal_places=2, max_digits=11, null=True)),
                ('unit', models.CharField(max_length=128, null=True)),
                ('suite', models.CharField(max_length=16)),
                ('job_id', models.CharField(max_length=16)),
            ],
        ),
    ]
