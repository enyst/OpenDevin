FROM python:3.11-slim as base


# install basic packages
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    vim \
    nano \
    unzip \
    zip \
    build-essential \
    openssh-server \
    sudo \
    bash \
    gcc \
    jq \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Setup SSH server
RUN mkdir -p -m0755 /var/run/sshd

# Python3, pip, and python3-venv are already included in the python:3.11-slim image
# Python and pip commands should already point to the correct version in this image

# install basic dependencies for CodeActAgent
RUN pip3 install --upgrade pip
RUN pip3 install jupyterlab notebook jupyter_kernel_gateway flake8
