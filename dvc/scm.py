import os

from dvc.exceptions import DvcException
from dvc.logger import Logger
from dvc.utils import fix_env


class SCMError(DvcException):
    pass


class FileNotInRepoError(DvcException):
    pass


class Base(object):
    def __init__(self, root_dir=os.curdir, project=None):
        self.project = project
        self.root_dir = root_dir

    @staticmethod
    def is_repo(root_dir):
        return True

    @staticmethod
    def is_submodule(root_dir):
        return True

    def ignore(self, path):
        pass

    def ignore_remove(self, path):
        pass

    def ignore_file(self):
        pass

    def ignore_list(self, p_list):
        return [self.ignore(path) for path in p_list]

    def add(self, paths):
        pass

    def commit(self, msg):
        pass

    def checkout(self, branch):
        pass

    def branch(self, branch):
        pass

    def brancher(self,
                 branches=None,
                 all_branches=False,
                 tags=None,
                 all_tags=False):
        if not branches and not all_branches \
           and not tags and not all_tags:
            yield ''
            return

        saved = self.active_branch()
        revs = []

        if branches is not None:
            revs.extend(branches)
        elif all_branches:
            revs.extend(self.list_branches())
        elif tags is not None:
            revs.extend(tags)
        elif all_tags:
            revs.extend(self.list_tags())
        else:
            revs.extend([saved])

        for rev in revs:
            self.checkout(rev)
            yield rev

        self.checkout(saved)

    def untracked_files(self):
        pass

    def is_tracked(self, path):
        pass

    def active_branch(self):
        pass

    def list_branches(self):
        pass

    def list_tags(self):
        pass

    def install(self):
        pass


class Git(Base):
    GITIGNORE = '.gitignore'
    GIT_DIR = '.git'

    def __init__(self, root_dir=os.curdir, project=None):
        super(Git, self).__init__(root_dir, project=project)

        import git
        from git.exc import InvalidGitRepositoryError
        try:
            self.repo = git.Repo(root_dir)
        except InvalidGitRepositoryError:
            msg = '{} is not a git repository'
            raise SCMError(msg.format(root_dir))

        # NOTE: fixing LD_LIBRARY_PATH for binary built by PyInstaller.
        # http://pyinstaller.readthedocs.io/en/stable/runtime-information.html
        env = fix_env(None)
        lp = env.get('LD_LIBRARY_PATH', None)
        self.repo.git.update_environment(LD_LIBRARY_PATH=lp)

    @staticmethod
    def is_repo(root_dir):
        return os.path.isdir(Git._get_git_dir(root_dir))

    @staticmethod
    def is_submodule(root_dir):
        return os.path.isfile(Git._get_git_dir(root_dir))

    @staticmethod
    def _get_git_dir(root_dir):
        return os.path.join(root_dir, Git.GIT_DIR)

    @property
    def dir(self):
        return self.repo.git_dir

    def ignore_file(self):
        return self.GITIGNORE

    def _get_gitignore(self, path):
        assert os.path.isabs(path)
        entry = os.path.basename(path)
        gitignore = os.path.join(os.path.dirname(path), self.GITIGNORE)

        if not gitignore.startswith(self.root_dir):
            raise FileNotInRepoError(path)

        return entry, gitignore

    def ignore(self, path):
        entry, gitignore = self._get_gitignore(path)

        ignore_list = []
        if os.path.exists(gitignore):
            ignore_list = open(gitignore, 'r').readlines()
            filtered = list(filter(lambda x: x.strip() == entry.strip(),
                                   ignore_list))
            if len(filtered) != 0:
                return

        msg = "Adding '{}' to '{}'.".format(os.path.relpath(path),
                                            os.path.relpath(gitignore))
        Logger.info(msg)

        content = entry
        if len(ignore_list) > 0:
            content = '\n' + content

        with open(gitignore, 'a') as fd:
            fd.write(content)

        if self.project is not None:
            self.project._files_to_git_add.append(os.path.relpath(gitignore))

    def ignore_remove(self, path):
        entry, gitignore = self._get_gitignore(path)

        if not os.path.exists(gitignore):
            return

        with open(gitignore, 'r') as fd:
            lines = fd.readlines()

        filtered = list(filter(lambda x: x.strip() != entry.strip(), lines))

        with open(gitignore, 'w') as fd:
            fd.writelines(filtered)

        if self.project is not None:
            self.project._files_to_git_add.append(os.path.relpath(gitignore))

    def add(self, paths):
        # NOTE: GitPython is not currently able to handle index version >= 3.
        # See https://github.com/iterative/dvc/issues/610 for more details.
        try:
            self.repo.index.add(paths)
        except AssertionError as exc:
            msg = 'Failed to add \'{}\' to git. You can add those files '
            msg += 'manually using \'git add\'. '
            msg += 'See \'https://github.com/iterative/dvc/issues/610\' '
            msg += 'for more details.'
            Logger.error(msg.format(str(paths)), exc)

    def commit(self, msg):
        self.repo.index.commit(msg)

    def checkout(self, branch, create_new=False):
        if create_new:
            self.repo.git.checkout('HEAD', b=branch)
        else:
            self.repo.git.checkout(branch)

    def branch(self, branch):
        self.repo.git.branch(branch)

    def untracked_files(self):
        files = self.repo.untracked_files
        return [os.path.join(self.repo.working_dir, fname) for fname in files]

    def is_tracked(self, path):
        return len(self.repo.git.ls_files(path)) != 0

    def active_branch(self):
        return self.repo.active_branch.name

    def list_branches(self):
        return [h.name for h in self.repo.heads]

    def list_tags(self):
        return [t.name for t in self.repo.tags]

    def install(self):
        hook = os.path.join(self.root_dir,
                            self.GIT_DIR,
                            'hooks',
                            'post-checkout')
        if os.path.isfile(hook):
            msg = 'Git hook \'{}\' already exists.'
            raise SCMError(msg.format(os.path.relpath(hook)))
        with open(hook, 'w+') as fd:
            fd.write('#!/bin/sh\nexec dvc checkout\n')
        os.chmod(hook, 0o777)


class Mercurial(Base):
    HGIGNORE = '.hgignore'
    HG_DIR = '.hg'

    def __init__(self, root_dir=os.curdir, project=None):
        super(Mercurial, self).__init__(root_dir, project=project)

        import hglib as hg

        try:
            self.hgclient = hg.open(root_dir)
        except hg.ServerError:
            msg = '{} is not a mercurial repository'
            raise SCMError(msg.format(root_dir))

    @staticmethod
    def is_repo(root_dir):
        return os.path.isdir(Mercurial._get_hg_dir(root_dir))

    @staticmethod
    def is_submodule(root_dir):
        return os.path.isfile(Mercurial._get_hg_dir(root_dir))

    @staticmethod
    def _get_hg_dir(root_dir):
        return os.path.join(root_dir, Mercurial.HG_DIR)

    @property
    def dir(self):
        return os.path.join (self.hgclient.root(), self.HG_DIR)

    def ignore_file(self):
        return self.HGIGNORE

    def _get_hgignore(self, path):
        assert os.path.isabs(path)
        entry = os.path.basename(path)
        hgignore = os.path.join(os.path.dirname(path), self.HGIGNORE)

        if not hgignore.startswith(self.root_dir):
            raise FileNotInRepoError(path)

        return entry, hgignore

    def ignore(self, path):
        entry, hgignore = self._get_hgignore(path)

        ignore_list = []
        if os.path.exists(hgignore):
            ignore_list = open(hgignore, 'r').readlines()
            filtered = list(filter(lambda x: x.strip() == entry.strip(),
                                   ignore_list))
            if len(filtered) != 0:
                return

        msg = "Adding '{}' to '{}'.".format(os.path.relpath(path),
                                            os.path.relpath(hgignore))
        Logger.info(msg)

        content = entry
        if len(ignore_list) > 0:
            content = '\n' + content

        with open(hgignore, 'a') as fd:
            fd.write(content)

        if self.project is not None:
            # NOTE: Can _files_to_git_add be changed to something more generic?
            self.project._files_to_git_add.append(os.path.relpath(hgignore))

    def ignore_remove(self, path):
        entry, hgignore = self._get_hgignore(path)

        if not os.path.exists(hgignore):
            return

        with open(hgignore, 'r') as fd:
            lines = fd.readlines()

        filtered = list(filter(lambda x: x.strip() != entry.strip(), lines))

        with open(hgignore, 'w') as fd:
            fd.writelines(filtered)

        if self.project is not None:
            self.project._files_to_git_add.append(os.path.relpath(hgignore))

    def add(self, paths):
        try:
            self.hgclient.add(paths)
        except AssertionError as exc:
            msg = 'Failed to add \'{}\' to mercurial. You can add those files '
            msg += 'manually using \'hg add\'. '
            Logger.error(msg.format(str(paths)), exc)

    def commit(self, msg):
        self.hgclient.commit(message=msg)

    def checkout(self, branch, create_new=False):
        if create_new:
            self.hgclient.branch(name=branch)
        else:
            self.hgclient.update(rev=branch)

    def branch(self, branch):
        self.hgclient.branch(name=branch)

    def untracked_files(self):
        files = [x[1] for x in self.hgclient.status(unknown=True)]
        return [os.path.join(self.hgclient.root(), fname) for fname in files]

    def is_tracked(self, path):
        return len(self.repo.git.ls_files(path)) != 0

    def active_branch(self):
        return self.hgclient.branch()

    def list_branches(self):
        return [x[0] for x in self.hgclient.branches()]

    def list_tags(self):
        return [x[0] for x in self.hgclient.tags()]

    def install(self):
        # TODO: implement mercurial install method
        # unfortunately I don't know the exact equivalent of the git post-checkout
        # hook in mercurial, it's possibly 'update' which is run after the update
        # command, but this is not quite the same as the git checkout command
#        hook = os.path.join(self.root_dir,
#                            self.HG_DIR,
#                            'hooks',
#                            'post-checkout')
#        if os.path.isfile(hook):
#            msg = 'Mercurial hook \'{}\' already exists.'
#            raise SCMError(msg.format(os.path.relpath(hook)))
#        with open(hook, 'w+') as fd:
#            fd.write('#!/bin/sh\nexec dvc checkout\n')
#        os.chmod(hook, 0o777)


def SCM(root_dir, no_scm=False, project=None):
    if Git.is_repo(root_dir) or Git.is_submodule(root_dir):
        return Git(root_dir, project=project)

    return Base(root_dir, project=project)
