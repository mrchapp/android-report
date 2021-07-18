#!/bin/bash -e

dir_parent=$(cd $(dirname $0); pwd)

# e.g.
# ./kernelreport.sh 5.10
# ./kernelreport.sh 5.10 5.10.40
ker_version="${1}"

if [ -z "${ker_version}" ]; then
    echo "Please run like this:"
    echo -e "\t${0} kernel"
    echo -e "\t${0} kernel exact_kernel_version"
    exit 1
fi

opt_check_ker_ver=""
if echo "$@" |grep "\-\-no-check-kernel-version"; then
    opt_check_ker_ver="--no-check-kernel-version"
fi

# Try to find if the exact_kernel_version is specified
exact_ker_version=${2:-"No"}
while true; do
    if [ "X${exact_ker_version}X" = "X--no-check-kernel-versionX" ]; then
        shift
    else
        break
    fi
    exact_ker_version=${2:-"No"}
done

if [ "X${exact_ker_version}" = "XNo" ]; then
    f_report="/tmp/kernelreport-${ker_version}.txt"
else
    f_report="/tmp/kernelreport-${ker_version}-${exact_ker_version}.txt"
fi
rm -f "${f_report}.scribble"

wget -c https://raw.githubusercontent.com/tom-gall/android-qa-classifier-data/master/flakey.txt -O /tmp/flakey.txt
${dir_parent}/../workspace-python3/bin/python ${dir_parent}/manage.py kernelreport ${opt_check_ker_ver} "${ker_version}" ${f_report} /tmp/flakey.txt "${exact_ker_version}"
if [ -f "${f_report}.scribble" ]; then
    cat "${f_report}.scribble" >> "${f_report}"
    echo "Please check the file of ${f_report} for report"
    rm -f "${f_report}.scribble"
else
    echo "Failed to generate the test report, Please check and try again"
fi
