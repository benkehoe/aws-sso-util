import argparse
import subprocess
import tempfile
import sys
from pathlib import Path
import shutil
import shlex
import contextlib

import click

REPO = "https://github.com/benkehoe/aws-sso-util"

def clone_repo(git_clone_origin, git_clone_branch, git_clone_args):
    temp_dir = tempfile.TemporaryDirectory(prefix="aws-sso-util")

    temp_dir_path = Path(temp_dir.name)

    git_command = ["git", "clone", git_clone_origin, str(temp_dir_path)]
    if git_clone_branch:
        git_command.extend(["--branch", git_clone_branch])
    else:
        #git_command.extend(["--branch", "macro/stable"])
        pass
    if git_clone_args:
        git_command.extend(shlex.split(git_clone_args))
    else:
        git_command.extend(["--depth", "1"])


    print(f"Running git cline: {shlex.join(git_command)}")
    result = subprocess.run(git_command)

    if result.returncode:
        print("git clone failed", file=sys.stderr)
        sys.exit(2)

    subprocess.run(f"ls -al {temp_dir_path}", shell=True)

    return temp_dir

@click.command("deploy-macro")
@click.option("--load-samconfig", help="Use an existing samconfig.toml file")
@click.option("--save-samconfig", help="Save the resulting samconfig.toml to a given path, or 'true' to save to the loaded file")
@click.option("--sam-build-args", help="A string of arguments to pass to 'sam build'")
@click.option("--sam-deploy-args", default="--guided", help="A string of arguments to pass to 'sam deploy'")
@click.option("--git-clone-branch")
@click.option("--git-clone-args", help="A string of arguments to pass to 'git clone'")
@click.option("--git-clone-origin", default=REPO)
@click.option("--existing-repo-dir", help="Use an existing repo path instead of a temporary clone")
def deploy_macro(
        load_samconfig,
        save_samconfig,
        sam_build_args,
        sam_deploy_args,
        git_clone_branch,
        git_clone_args,
        git_clone_origin,
        existing_repo_dir):
    if existing_repo_dir:
        repo_dir = contextlib.nullcontext(existing_repo_dir)
    else:
        repo_dir = clone_repo(git_clone_origin, git_clone_branch, git_clone_args)

    with repo_dir as repo_dir_path:
        repo_dir_path = Path(repo_dir_path)
        working_dir = repo_dir_path / "macro"
        if not working_dir.is_dir():
            print(f"{working_dir} is not a valid directory", file=sys.stderr)
            sys.exit(1)

        if load_samconfig:
            load_samconfig = Path(load_samconfig)
            if not load_samconfig.is_file():
                print(f"{load_samconfig} is not a valid file", file=sys.stderr)
                sys.exit(1)
            print(f"Copying samconfig.toml from {load_samconfig} to {working_dir}")
            shutil.copy2(load_samconfig.resolve(), working_dir / "samconfig.toml")

        run_kwargs = {
            "cwd": working_dir
        }

        sam_build_command = ["sam", "build", "--use-container"]
        if sam_build_args:
            sam_build_command.extend(shlex.split(sam_build_args))

        print(f"Running sam build: {shlex.join(sam_build_command)}")
        result = subprocess.run(sam_build_command, **run_kwargs)

        if result.returncode:
            print("sam build failed", file=sys.stderr)
            sys.exit(2)

        sam_deploy_command = ["sam", "deploy"]
        if sam_deploy_args:
            sam_deploy_command.extend(shlex.split(sam_deploy_args))

        print(f"Running sam deploy: {shlex.join(sam_deploy_command)}")
        result = subprocess.run(sam_deploy_command, **run_kwargs)

        if result.returncode:
            print("sam deploy failed", file=sys.stderr)
            sys.exit(2)

        if save_samconfig:
            if save_samconfig.lower() in ["true", "1"]:
                if not load_samconfig:
                    print(f"--save-samconfig {save_samconfig} set but --load-samconfig not provided")
                    sys.exit(1)
                save_samconfig = load_samconfig
            save_samconfig = Path(save_samconfig)
            print(f"Writing samconfig.toml to {save_samconfig}")
            save_samconfig.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(working_dir / "samconfig.toml", save_samconfig)

if __name__ == "__main__":
    deploy_macro(prog_name="python -m aws_sso_util.cli.deploy_macro")  #pylint: disable=unexpected-keyword-arg,no-value-for-parameter
