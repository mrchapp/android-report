# -*- coding: utf-8 -*-
# Generated by Django 1.11.5 on 2018-01-07 13:57
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('report', '0014_auto_20171130_1628'),
    ]

    operations = [
        migrations.AddField(
            model_name='bug',
            name='build_no_fixed',
            field=models.CharField(blank=True, default='', max_length=8),
        ),
    ]
