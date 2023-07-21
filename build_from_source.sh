#!/bin/bash

# This script will build aws-sso-lib and aws-sso-cli from source after you have run:
# git clone https://github.com/benkehoe/aws-sso-util
#
# Reference: https://github.com/benkehoe/aws-sso-util/issues/58

poetry --version > /dev/null 2>&1
if [ "$?" -ne "0" ] ; then
    echo
    echo "poetry program not found."
    echo "Please first install 'poetry' from https://install.python-poetry.org/"
    echo "For example: wget -O install-poetry.py https://install.python-poetry.org/"
    echo
    exit 1
fi

set -e
prefix="aws_sso"
dname=$(dirname $0)
root_dir=$(cd ${dname}; pwd)

build() {
    dir=$1
    echo
    echo "(*) Running: 'poetry build' in ${dir} directory..."
    cd ${root_dir}
    cd ${dir}
    poetry build

    name="${prefix}_${dir}"
    version=$(awk -F\" '/version/ {print $2}' pyproject.toml)
    wheel="${dir}/dist/${name}-${version}-py3-none-any.whl"
    if [ -f ${wheel} ] ; then
        echo
        echo "Wheel file not created: ${wheel}"
        echo
        exit 1
    fi
}

install() {
    dir=$1
    code=$2
    cd ${root_dir}
    name="${prefix}_${code}"
    wheel="${dir}/dist/${name}-${version}-py3-none-any.whl"
    echo
    echo "(*) Running: pip install --user ${wheel}"
    pwd
    pip install --user ${wheel}
}


build lib
install lib lib

build cli
install cli util

