# Copyright (c) ACSONE SA/NV 2019
# Distributed under the MIT License (http://opensource.org/licenses/MIT).

import subprocess

from .. import github
from ..manifest import bump_manifest_version, git_modified_addons
from ..queue import getLogger, task
from ..version_branch import make_merge_bot_branch, parse_merge_bot_branch
from .main_branch_bot import main_branch_bot_actions

_logger = getLogger(__name__)


@task()
def merge_bot_start(org, repo, pr, username, bumpversion=None, dry_run=False):
    # TODO error handling
    with github.login() as gh:
        if not github.git_user_can_push(gh.repository(org, repo), username):
            return
        gh_pr = gh.pull_request(org, repo, pr)
        target_branch = gh_pr.base.ref
    with github.temporary_clone(org, repo, target_branch):
        # create merge bot branch from PR and rebase it on target branch
        merge_bot_branch = make_merge_bot_branch(pr, target_branch)
        subprocess.check_output(
            ["git", "fetch", "origin", f"pull/{pr}/head:{merge_bot_branch}"]
        )
        subprocess.check_output(["git", "checkout", merge_bot_branch])
        subprocess.check_output(["git", "rebase", "--autosquash", target_branch])
        # run main branch bot actions
        main_branch_bot_actions(org, repo, target_branch, dry_run)
        if bumpversion:
            for addon in git_modified_addons(".", target_branch):
                bump_manifest_version(addon, bumpversion, git_commit=True)
        # push
        subprocess.check_call(["git", "push", "--force", "origin", merge_bot_branch])


@task()
def merge_bot_status_failure(org, repo, merge_bot_branch, sha):
    with github.temporary_clone(org, repo, merge_bot_branch):
        head_sha = github.git_get_head_sha()
        if head_sha != sha:
            # the branch has evolved, this means that this status
            # does not correspond to the last commit of the bot, ignore it
            return
        pr, target_branch = parse_merge_bot_branch(merge_bot_branch)
        with github.login() as gh:
            gh_pr = gh.pull_request(org, repo, pr)
            github.gh_call(
                gh_pr.create_comment,
                f"Merge command aborted due to a red status `{merge_bot_branch}`.",
            )
            # TODO delete merge_bot_branch?


@task()
def merge_bot_status_success(org, repo, merge_bot_branch, sha):
    with github.temporary_clone(org, repo, merge_bot_branch):
        head_sha = github.git_get_head_sha()
        if head_sha != sha:
            # the branch has evolved, this means that this status
            # does not correspond to the last commit of the bot, ignore it
            return
        pr, target_branch = parse_merge_bot_branch(merge_bot_branch)
        subprocess.check_call(["git", "checkout", target_branch])
        subprocess.check_call(
            ["git", "merge", "--no-ff", "--no-edit", merge_bot_branch]
        )
        subprocess.check_call(["git", "push", "origin", target_branch])
        subprocess.check_call(["git", "push", "origin", f":{merge_bot_branch}"])
        with github.login() as gh:
            gh_pr = gh.pull_request(org, repo, pr)
            merge_sha = github.git_get_head_sha()
            github.gh_call(gh_pr.create_comment, f"Merged at {merge_sha}.")
            github.gh_call(gh_pr.close)
