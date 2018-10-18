#!/usr/bin/python

"""
Package YoDa related repos using fpm

repos.jon format
    name
        fork
        branch
        branch_is_version (optinal, default version from branch_is_version, overridden by fpm.json)
        version (optional, default)

fpm.json format
    no single letter keys
    list of values are converted in multiple options (or args)
    boolean values: when true, add key
    when the commands are generated, all values are templated with the whole fpm dict
        (e.g. so you can use '{name}' template)
    some options
        version (default from repos.json)
        license
        description
        architecture (default noarch)
        iteration (default last commit timestamp.hash)
        url (default url from repo)
        name (default name from repos.json)
        input-type (default dir)
        ARGS: passed as arg(s) to fpm
"""

from git import Repo
import logging
import os
import shutil
import json
import subprocess

GITHUB_GIT = "https://github.com/{fork}/{name}"
PKG_AREA = '/tmp/yoda-packages'  # to clone epos etc
PKG_SUBDIR = 'packages'  # subdir of PKG_AREA to agtehr all packages
REPOS_JSON = 'repos.json'
FPM_JSON = 'fpm.json'
CWD = os.getcwd()
DEFAULT_ARCH = 'noarch'
DEFAULT_PKG = 'rpm'
FPM = 'fpm'
ARGS_KW = 'ARGS'
DEFAULT_INPUT_TYPE = 'dir'


def prep_repo(repo_d, wipe=False):
    """
    repo_d is a dict with repo details
    returs GitPyhon Repo instance
    """
    repo_path = os.path.join(PKG_AREA, repo_d['name'])
    url = GITHUB_GIT.format(**repo_d)

    # just wipe for now?
    if wipe and os.path.isdir(repo_path):
        shutil.rmtree(repo_path)

    if os.path.isdir(repo_path):
        repo = Repo(repo_path)
        logging.debug("Using existing repo %s url %s in %s", repo, url, repo_path)
    else:
        repo = Repo.clone_from(url, repo_path)
        logging.debug("Cloned repo %s url %s in %s", repo, url, repo_path)

    branch = getattr(repo.remotes.origin.refs, repo_d['branch'])

    repo.head.reference = branch
    repo.head.reset(index=True, working_tree=True)
    logging.debug("Switched to branch name %s (%s)", repo_d['branch'], branch)

    return repo


def gather_instructions(name, repo, version=None):
    """
    Get relevant instruction info
    Returns a dict with fpm options
    """
    # for now, we only have this locally
    # TODO: check in repo first
    ginst = os.path.join(CWD, 'instructions', name)
    linst = os.path.join(repo.working_dir, 'packaging')
    if os.path.isdir(linst):
        inst = linst
        logging.debug("Local instructions found at %s", linst)
    else:
        logging.debug("No local instructions found at %s", linst)
        if os.path.isdir(ginst):
            inst = ginst
            logging.debug("Instructions found at %s", ginst)
        else:
            logging.error("No instructions found at %s or %s", linst, ginst)

    if not os.path.isdir(inst):
        raise Exception("No instructions path found")

    fpm_json = os.path.join(inst, FPM_JSON)
    if not os.path.isfile(fpm_json):
        raise Exception("No FPM instructions {} found".format(fpm_json))

    with open(fpm_json, 'r') as f:
        fpm = json.load(f)
        for k in fpm.keys():
            if len(k) == 1:
                raise Exception("Found single letter %s (i.e. short option)" % k)

    # check for before/after install/remove/upgrade scripts
    for op in ['install', 'remove', 'upgrade']:
        for when in ['before', 'after']:
            opname = '{}-{}'.format(when, op)
            script = os.path.join(inst, )
            if os.path.isfile(script):
                logging.debug("Found %s script %s", opname, script)
                fpm[opname] = script

    last_commit = repo.commit()
    # last commit tiestamp+hash as iteration
    fpm.setdefault('iteration', "{}.{}".format(last_commit.committed_date, last_commit.hexsha[:8]))

    fpm.setdefault('url', repo.remote().url)
    fpm.setdefault('name', name)
    fpm.setdefault('architecture', DEFAULT_ARCH)
    fpm.setdefault('input-type', DEFAULT_INPUT_TYPE)

    got_version = fpm.setdefault('version', version)
    if got_version is None:
        raise Exception("No version for " + name)

    logging.debug("Gathered fpm options %s", fpm)
    return fpm


def run_fpm(fpm):
    """
    Actually run fpm
    """

    pkgdir = os.path.join(PKG_AREA, PKG_SUBDIR)
    os.makedirs(pkgdir)

    cmds = [
        FPM,
        '--force',
        '--output-type', DEFAULT_PKG,
        '--package', pkgdir,
    ]
    args = []
    for orig_k, origs in fpm.items():
        k = "--" + orig_k
        if not isinstance(origs, (list, tuple)):
            origs = [origs]
        for orig_v in origs:
            if isinstance(orig_v, bool):
                if orig_v:
                    cmds.append(k)
            else:
                v = orig_v.format(**fpm)
                if orig_k == ARGS_KW:
                    args.append(v)
                else:
                    cmds.extend([k, v])

    # args last
    cmds.extend(args)

    try:
        out = subprocess.check_output(cmds, stderr=subprocess.STDOUT)
        logging.debug("Fpm ran %s (possibly unsafe cmd %s) with output %s", cmds, " ".join(cmds), out)
    except subprocess.CalledProcessError as e:
        logging.error("Failed to run fpm with exitcode %s and output %s", e.returncode, e.output)
        raise


def make_package(repo_d):
    """
    - Clone / clean / checkout branch
    - Gather repo specific data
    - Generate fpm command
    - Run it
    """
    name = repo_d['name']
    logging.debug("Start make_packge for repo %s (%s)", name, repo_d)
    repo = prep_repo(repo_d)

    if repo_d.get('branch_is_version', False):
        logging.info("branch_is_version")
        bversion = repo_d['branch']
        logging.debug("branch_is_version sets default version to %s", bversion)
    else:
        bversion = None
    version = repo_d.get('version', bversion)
    fpm = gather_instructions(name, repo, version=version)

    os.chdir(repo.working_dir)
    pkgs = run_fpm(fpm)

    # just be bice
    os.chdir(CWD)


def parse_repos():
    """
    Parse the repos.json
    """
    with open(REPOS_JSON, 'r') as f:
        repos = json.load(f)
        res = []
        for k in sorted(repos.keys()):
            v = repos[k]
            v['name'] = k
            res.append(v)
        logging.debug("Got repos %s from %s", res, REPOS_JSON)
        return res

def main():
    repos = parse_repos()

    for repo in repos:
        os.chdir(CWD)
        make_package(repo)

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
