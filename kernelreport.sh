#!/bin/bash -e

dir_parent=$(cd $(dirname $0); pwd)

# e.g.
# ./kernelreport.sh 5.10
# ./kernelreport.sh 5.10 5.10.40
ker_version="${1}"
exact_ker_version=${2:-"No"}

if [ -z "${ker_version}" ]; then
    echo "Please run like this:"
    echo -e "\t${0} [4.4|4.9|4.14|4.19|5.4|5.10|EAP510|EAP54]"
    echo -e "\t${0} [4.4|4.9|4.14|4.19|5.4|5.10|EAP510|EAP54] exact_kernel_version"
    exit 1
fi
if [ "X${exact_ker_version}" = "XNo" ]; then
    f_report="/tmp/kernelreport-${ker_version}.txt"
else
    f_report="/tmp/kernelreport-${exact_ker_version}.txt"
fi

wget -c https://raw.githubusercontent.com/tom-gall/android-qa-classifier-data/master/flakey.txt -O /tmp/flakey.txt
${dir_parent}/../workspace-python3/bin/python ${dir_parent}/manage.py kernelreport "${ker_version}" ${f_report} /tmp/flakey.txt "${exact_ker_version}"
cat ${f_report}.scribble >> ${f_report}
echo "Please check the file of ${f_report} for report"
rm -f ${f_report}.scribble
