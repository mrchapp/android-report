# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re

basic_weekly = { # job_name: ['test_suite', ],
                        #"basic": [ "meminfo", 'meminfo-first', 'meminfo-second', "busybox", "ping", "linaro-android-kernel-tests", "tjbench"],
                        "basic": [ "busybox", "ping", "linaro-android-kernel-tests", "tjbench"],
                        "weekly": [ 'media-codecs', 'piglit-gles2', 'piglit-gles3', 'piglit-glslparser', 'piglit-shader-runner', 'stringbench', 'libc-bench'],
                     }

optee = { # job_name: ['test_suite', ],
          "optee-xtest": [ "optee-xtest"],
        }

benchmarks_common = {  # job_name: {'test_suite':['test_case',]},
                "boottime": {
                              #'boottime-analyze': ['KERNEL_BOOT_TIME_avg', 'ANDROID_BOOT_TIME_avg', 'TOTAL_BOOT_TIME_avg' ],
                              'boottime-fresh-install': ['KERNEL_BOOT_TIME_avg', 'ANDROID_BOOT_TIME_avg', 'TOTAL_BOOT_TIME_avg' ],
                              'boottime-reboot': ['KERNEL_BOOT_TIME_avg', 'ANDROID_BOOT_TIME_avg', 'TOTAL_BOOT_TIME_avg' ],
                            },
                "basic": {
                            "meminfo-first": [ 'MemTotal', 'MemFree', 'MemAvailable'],
                            #"meminfo": [ 'MemTotal', 'MemFree', 'MemAvailable'],
                            "meminfo-second": [ 'MemTotal', 'MemFree', 'MemAvailable'],
                         },

                'monkey': { 'monkey': ['monkey-network-stats'] },
                #'andebenchpro2015': {'andebenchpro2015':[] },
                'antutu6': { 'antutu6': ['antutu6-sum-mean'] },
                #'applications': {},
                'benchmarkpi': {'benchmarkpi': ['benchmarkpi-mean',]},
                'caffeinemark': {'caffeinemark': ['Caffeinemark-Collect-score-mean', 'Caffeinemark-Float-score-mean', 'Caffeinemark-Loop-score-mean',
                                      'Caffeinemark-Method-score-mean', 'Caffeinemark-score-mean', 'Caffeinemark-Sieve-score-mean', 'Caffeinemark-String-score-mean']},
                'cf-bench': {'cf-bench': ['cfbench-Overall-Score-mean', 'cfbench-Java-Score-mean', 'cfbench-Native-Score-mean']},
                'gearses2eclair': {'gearses2eclair': ['gearses2eclair-mean',]},
                'geekbench4': {'geekbench4': ['Geekbench4-Multi-Core-mean', 'Geekbench4-Single-Core-mean']},
                #'geekbench3': {'geekbench3': ['geekbench-multi-core-mean', 'geekbench-single-core-mean']},
                'javawhetstone': {'javawhetstone': ['javawhetstone-MWIPS-mean', 'javawhetstone-N1-float-mean', 'javawhetstone-N2-float-mean', 'javawhetstone-N3-if-mean', 'javawhetstone-N4-fixpt-mean',
                                       'javawhetstone-N5-cos-mean', 'javawhetstone-N6-float-mean', 'javawhetstone-N7-equal-mean', 'javawhetstone-N8-exp-mean',]},
                'jbench': {'jbench': ['jbench-mean',]},
                'linpack': {'linpack': ['Linpack-MFLOPSSingleScore-mean', 'Linpack-MFLOPSMultiScore-mean', 'Linpack-TimeSingleScore-mean', 'Linpack-TimeMultiScore-mean']},
                'quadrantpro': {'quadrantpro': ['quadrandpro-benchmark-memory-mean', 'quadrandpro-benchmark-mean', 'quadrandpro-benchmark-g2d-mean', 'quadrandpro-benchmark-io-mean',
                                     'quadrandpro-benchmark-cpu-mean', 'quadrandpro-benchmark-g3d-mean',]},
                'rl-sqlite': {'rl-sqlite': ['RL-sqlite-Overall-mean',]},
                'scimark': {'scimark': ['scimark-FFT-1024-mean', 'scimark-LU-100x100-mean', 'scimark-SOR-100x100-mean', 'scimark-Monte-Carlo-mean', 'scimark-Composite-Score-mean',]},
                'vellamo3': {'vellamo3': ['vellamo3-Browser-total-mean', 'vellamo3-Metal-total-mean', 'vellamo3-Multi-total-mean', 'vellamo3-total-score-mean',]},

                'glbenchmark25': {'glbenchmark25': ['Fill-rate-C24Z16-mean', 'Fill-rate-C24Z16-Offscreen-mean',
                                    'GLBenchmark-2.1-Egypt-Classic-C16Z16-mean', 'GLBenchmark-2.1-Egypt-Classic-C16Z16-Offscreen-mean',
                                    'GLBenchmark-2.5-Egypt-HD-C24Z16-Fixed-timestep-mean', 'GLBenchmark-2.5-Egypt-HD-C24Z16-Fixed-timestep-Offscreen-mean',
                                    'GLBenchmark-2.5-Egypt-HD-C24Z16-mean', 'GLBenchmark-2.5-Egypt-HD-C24Z16-Offscreen-mean',
                                    'Triangle-throughput-Textured-C24Z16-Fragment-lit-mean', 'Triangle-throughput-Textured-C24Z16-Offscreen-Fragment-lit-mean',
                                    'Triangle-throughput-Textured-C24Z16-mean', 'Triangle-throughput-Textured-C24Z16-Offscreen-mean',
                                    'Triangle-throughput-Textured-C24Z16-Vertex-lit-mean', 'Triangle-throughput-Textured-C24Z16-Offscreen-Vertex-lit-mean',
                                   ],},
             }
less_is_better_measurement = [
                              'KERNEL_BOOT_TIME_avg', 'ANDROID_BOOT_TIME_avg', 'TOTAL_BOOT_TIME_avg',
                              'benchmarkpi-mean',
                              'Linpack-TimeSingleScore-mean', 'Linpack-TimeMultiScore-mean', 'RL-sqlite-Overall-mean'
                             ]

# test_suite is "vts-test"
vts = [
        'vts-hal',
        'vts-kernel-kselftest',
        'vts-kernel-ltp',
        'vts-kernel-part1',
        'vts-library',
        'vts-performance',
      ]

# test_suite is the same as job name
cts_v7a = [ 'cts-focused1-armeabi-v7a',
            'cts-focused2-armeabi-v7a',
            'cts-media-armeabi-v7a',
            'cts-media2-armeabi-v7a',
            'cts-opengl-armeabi-v7a',
            'cts-part1-armeabi-v7a',
            'cts-part2-armeabi-v7a',
            'cts-part3-armeabi-v7a',
            'cts-part4-armeabi-v7a',
            'cts-part5-armeabi-v7a',
          ]

# test_suite is the same as job name
cts_v8a = [ 'cts-focused1-arm64-v8a',
            'cts-focused2-arm64-v8a',
            'cts-media-arm64-v8a',
            'cts-media2-arm64-v8a',
            'cts-opengl-arm64-v8a',
            'cts-part1-arm64-v8a',
            'cts-part2-arm64-v8a',
            'cts-part3-arm64-v8a',
            'cts-part4-arm64-v8a',
            'cts-part5-arm64-v8a',
          ]

android_snapshot_url_base = "http://snapshots.linaro.org/android"
ci_job_url_base = 'https://ci.linaro.org/job'
android_build_config_url_base = "https://android-git.linaro.org/android-build-configs.git/plain"
template_url_prefix = "https://git.linaro.org/qa/test-plans.git/plain/android/"

TEST_RESULT_XML_NAME = 'test_result.xml'

pat_ignore = re.compile(".*("
                        "-stderr"
                        "|-sigma"
                        "|-max"
                        "|-min"
                        "|-itr\d+"
                        ")$")

                        #"|regression_\d+"

names_ignore = ["test-attachment",
                "test-skipped",
                'install-fastboot', 'install-adb',
                "subtests-fail-rate", 'test-cases-fail-rate', # "regression_4003_XTS", "regression_4003_NO_XTS",
                "tradefed-test-run", "check-adb-connectivity",
                "3D-mean","Overall_Score-mean", "Memory_Bandwidth_Add_Multi_Core-mean", "Platform-mean", "Memory_Bandwidth-mean", "Memory_Bandwidth_Copy_Single_Core-mean", "Memory_Latency_64M_range-mean", "Memory_Bandwidth_Scale_Single_Core-mean", "Memory_Bandwidth_Copy_Multi_Core-mean", "Storage-mean", "Memory_Bandwidth_Triad_Single_Core-mean", "CoreMark-PRO_Base-mean", "Memory_Bandwidth_Add_Single_Core-mean", "CoreMark-PRO_Peak-mean", "Memory_Bandwidth_Scale_Multi_Core-mean", "Memory_Latency-mean", "Memory_Bandwidth_Triad_Multi_Core-mean",
                "BOOTTIME_LOGCAT_ALL_COLLECT", "BOOTTIME_LOGCAT_EVENTS_COLLECT", "SERVICE_STARTED_ONCE", "BOOTTIME_ANALYZE", "BOOTTIME_DMESG_COLLECT", 'BOOTANIM_TIME', 'FS_MOUNT_DURATION', 'FS_MOUNT_TIME', 'KERNEL_BOOT_TIME', 'TOTAL_BOOT_TIME', 'ANDROID_SERVICE_START_TIME', 'ANDROID_BOOT_TIME', 'ANDROID_UI_SHOWN', 'SURFACEFLINGER_BOOT_TIME', 'INIT_TO_SURFACEFLINGER_START_TIME',
                "start_bootchart", "enabled_bootchart", "stop_bootchart", "rm_start_file", "generate-bootchart-graphic",
               ]

job_status_dict = {0: "Submitted",
                   1: "Running",
                   2: "Complete",
                   3: "Incomplete",
                   4: "Canceled",
                   5: "NoPermission",
                  }

job_status_string_int = dict((v,k) for k,v in job_status_dict.iteritems())
job_priority_list = ['high', 'medium', 'low']

DEFAULT_LAVA_USER = "yongqin.liu"

DEFAULT_LCR_BUILD_NAME = "android-lcr-reference-hikey-p"

build_configs = {
    'android-lcr-reference-am65x-p': {
                                'optee_supported': False,
                                'v8a_supported' : True,
                                'kernel_makefile_url_with_commitid': 'http://git.ti.com/ti-linux-kernel/ti-linux-kernel/blobs/raw/%s/Makefile',
                                'kernel_src_path': 'kernel/ti/4.19',
                                'platform_name': 'AM65XEVM',
                                },
    'android-lcr-reference-x15-p': {
                                'optee_supported': False,
                                'v8a_supported' : False,
                                'kernel_makefile_url_with_commitid': 'http://git.ti.com/ti-linux-kernel/ti-linux-kernel/blobs/raw/%s/Makefile',
                                'kernel_src_path': 'kernel/ti/4.19',
                                'platform_name': 'AM65XEVM',
                                },
    'android-lcr-reference-hikey-p': {
                                'optee_supported': True,
                                'v8a_supported' : True,
                                'kernel_makefile_url_with_commitid': 'https://android-git.linaro.org/kernel/hikey-linaro.git/plain/Makefile?id=%s',
                                'kernel_src_path': 'kernel/linaro/hisilicon-4.14',
                                'platform_name': 'HiKey',
                                },
    'android-lcr-reference-hikey960-p': {
                                'optee_supported': True,
                                'v8a_supported' : True,
                                'kernel_makefile_url_with_commitid': 'https://android-git.linaro.org/kernel/hikey-linaro.git/plain/Makefile?id=%s',
                                'kernel_src_path': 'kernel/linaro/hisilicon-4.14',
                                'platform_name': 'HiKey960',
                                },
}

def get_basic_optee_weekly_tests(build_name):
    basic_optee_weekly = basic_weekly.copy()
    build_config = build_configs.get(build_name)
    if build_config and build_config.get('optee_supported'):
        basic_optee_weekly.update(optee)
    return basic_optee_weekly

def get_cts_tests(build_name):
    build_config = build_configs.get(build_name)
    basic_optee_weekly = basic_weekly.copy()
    if build_config and build_config.get('v8a_supported'):
        return [] + cts_v7a + cts_v8a
    else:
        return [] + cts_v7a

def get_kernel_makefile_url(build_name):
    build_config = build_configs.get(build_name)
    if build_config and build_config.get('kernel_makefile_url_with_commitid'):
       return build_config.get('kernel_makefile_url_with_commitid')
    else:
        return None

def get_kernel_src_path(build_name):
    build_config = build_configs.get(build_name)
    if build_config and build_config.get('kernel_src_path'):
       return build_config.get('kernel_src_path')
    else:
        return None

def get_platform_name(build_name):
    build_config = build_configs.get(build_name)
    if build_config and build_config.get('platform_name'):
       return build_config.get('platform_name')
    else:
        return None
