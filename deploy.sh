#!/bin/bash -ex

if [ "/*" = "$0" ]; then
    echo "Please run this script with absolute path"
    exit 1
fi

if [ -n "$1" ]; then
    work_root=$1
fi
if [ -d "${work_root}" ]; then
    work_root=$(cd ${work_root}; pwd)
elif [ -d /sata250/django_instances ]; then
    work_root="/sata250/django_instances"
elif [ -d /SATA3/django_instances ]; then
    work_root="/SATA3/django_instances"
elif [ -d /home/yongqin.liu/django_instance ]; then
    work_root="/home/yongqin.liu/django_instance"
else
    echo "Please set the path for work_root"
    exit 1
fi

instance_name="lcr-report"
instance_report_app="report"
instance_dir="${work_root}/${instance_name}"

virenv_dir="${work_root}/workspace-python3"
mkdir -p ${virenv_dir}
cd ${virenv_dir}
# https://pip.pypa.io/en/latest/installing/#installing-with-get-pip-py
if [ ! -f get-pip.py ]; then
   curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
fi
sudo python3 get-pip.py

sudo apt-get update
#sudo apt-get install python-django-auth-ldap
## dependency for python-ldap
sudo apt-get install libsasl2-dev python-dev python3-dev libldap2-dev libssl-dev gcc libjpeg-dev libpq-dev
#sudo apt-get install libtiff5-dev libjpeg8-dev zlib1g-dev libfreetype6-dev liblcms2-dev libwebp-dev libharfbuzz-dev libfribidi-dev tcl8.6-dev tk8.6-dev python-tk
# install for apache and wsgi packages
sudo apt-get install python3-pip apache2 libapache2-mod-wsgi-py3
# https://virtualenv.pypa.io/en/stable/
sudo pip install virtualenv
virtualenv --python=python3 ${virenv_dir}
source ${virenv_dir}/bin/activate

#(ENV)$ deactivate
#$ rm -r /path/to/ENV

#https://docs.djangoproject.com/en/1.11/topics/install/#installing-official-release
pip install Django==1.11.17 pyaml django-crispy-forms python-ldap django-auth-ldap requests reportlab psycopg2 python-dateutil
#pip install Django==1.11.8
#pip install Django==3.0.8
#pip install pyaml
#pip install django-crispy-forms==1.8.1
#pip install python-ldap # will install the 3.0 version
# https://django-auth-ldap.readthedocs.io/en/latest/install.html
#pip install django-auth-ldap # needs python-ldap >= 3.0
#pip install bugzilla
#pip install requests
#pip install reportlab
## pip install Pillow
## pip install rst2pdf

# https://docs.djangoproject.com/en/1.11/intro/tutorial01/
python3 -m django --version
#python manage.py startapp ${instance_report_app}
# django-admin startproject ${instance_name}
cd ${work_root}
if [ -d lcr-report ]; then
    cd lcr-report && git pull && cd -
else
    git clone https://github.com/liuyq/android-report.git lcr-report
fi

cd lcr-report
mkdir -p datafiles/logfiles/
sudo chown -R :www-data datafiles
sudo chmod 775 datafiles
sudo chmod 775 datafiles/logfiles
if [ -n "$(ls -A datafiles/logfiles)" ]; then
    sudo chmod 664 datafiles/logfiles/*
    sudo chown ${USER}: datafiles/logfiles/*
fi
rm -fr datafiles/db.sqlite3
python3 manage.py migrate
# for apache admin display
python3 manage.py collectstatic || true
python3 manage.py createsuperuser
echo "Please access the site via http://127.0.0.1:8000/lkft"
echo "And you still need to update the bugzilla, qa-report tokens to resubmit job or create bugs"
python3 manage.py runserver 0.0.0.0:8000

# python  manage.py collectstatic
# By running makemigrations, you’re telling Django that you’ve made some changes to your models (in this case,
# you’ve made new ones) and that you’d like the changes to be stored as a migration.
# python manage.py makemigrations report

# The migrate command looks at the INSTALLED_APPS setting and creates any necessary database tables according to the database settings
# in your mysite/settings.py file and the database migrations shipped with the app (we’ll cover those later)
# Need to run after makemigrations so that the tables for report could be created
# python manage.py migrate

# There’s a command that will run the migrations for you and manage your database schema automatically - that’s called migrate,
# and we’ll come to it in a moment - but first, let’s see what SQL that migration would run.
# The sqlmigrate command takes migration names and returns their SQL:
# Only shows the sql script, not creation
# python manage.py sqlmigrate report 0002

# cp db.sqlite3 db.sqlite3.bak.$(date +%Y%m%d-%H%M%S)
# scp android:/android/django_instances/lcr-report/db.sqlite3 ./
# cat jobs.txt |awk '{print $2}' >job-ids.txt
# sqlite3 db.sqlite3 "select * from report_testcase where job_id = 99965 ORDER BY name;"
# sqlite3 db.sqlite3 "delete from report_testcase where job_id = 99859;"


## with new db.sqlite3 file
## 1. remove the reference for the app in the lcr/urls.py
## 2. run python manage.py migrate to generate a new database
## 3. python manage.py createsuperuser to create a new user
## 4. setup build configs, lava uses from the admin ui
## 5. restartwith python manage.py runserver 0.0.0.0:9000
