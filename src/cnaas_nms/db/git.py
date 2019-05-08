import enum
import os
from typing import Set, Tuple

from git import Repo
from git import InvalidGitRepositoryError, NoSuchPathError
from git.exc import NoSuchPathError
import yaml

from cnaas_nms.db.exceptions import ConfigException, RepoStructureException
from cnaas_nms.tools.log import get_logger
from cnaas_nms.db.settings import get_settings, SettingsSyntaxError, DIR_STRUCTURE
from cnaas_nms.db.device import Device, DeviceType
from cnaas_nms.db.session import sqla_session

logger = get_logger()


class RepoType(enum.Enum):
    TEMPLATES = 0
    SETTINGS = 1

    @classmethod
    def has_value(cls, value):
        return any(value == item.value for item in cls)

    @classmethod
    def has_name(cls, value):
        return any(value == item.name for item in cls)


def get_repo_status(repo_type: RepoType = RepoType.TEMPLATES) -> str:
    with open('/etc/cnaas-nms/repository.yml', 'r') as db_file:
        repo_config = yaml.safe_load(db_file)

    if repo_type == RepoType.TEMPLATES:
        local_repo_path = repo_config['templates_local']
        remote_repo_path = repo_config['templates_remote']
    elif repo_type == RepoType.SETTINGS:
        local_repo_path = repo_config['settings_local']
        remote_repo_path = repo_config['settings_remote']
    else:
        raise ValueError("Invalid repository")

    try:
        local_repo = Repo(local_repo_path)
        return 'Commit {} by {} at {}\n'.format(
            local_repo.head.commit.name_rev,
            local_repo.head.commit.committer,
            local_repo.head.commit.committed_datetime
        )
    except (InvalidGitRepositoryError, NoSuchPathError) as e:
        return 'Repository is not yet cloned from remote'


def refresh_repo(repo_type: RepoType = RepoType.TEMPLATES) -> str:
    """Refresh the repository for repo_type

    Args:
        repo_type: Which repository to refresh

    Returns:
        String describing what was updated.

    Raises:
        cnaas_nms.db.settings.SettingsSyntaxError
    """

    with open('/etc/cnaas-nms/repository.yml', 'r') as db_file:
        repo_config = yaml.safe_load(db_file)

    if repo_type == RepoType.TEMPLATES:
        local_repo_path = repo_config['templates_local']
        remote_repo_path = repo_config['templates_remote']
    elif repo_type == RepoType.SETTINGS:
        local_repo_path = repo_config['settings_local']
        remote_repo_path = repo_config['settings_remote']
    else:
        raise ValueError("Invalid repository")

    ret = ''
    changed_files: Set[str] = set()
    try:
        local_repo = Repo(local_repo_path)
        prev_commit = local_repo.commit().hexsha
        diff = local_repo.remotes.origin.pull()
        for item in diff:
            ret += 'Commit {} by {} at {}\n'.format(
                item.commit.name_rev,
                item.commit.committer,
                item.commit.committed_datetime
            )
            diff_files = local_repo.git.diff(
                    '{}..{}'.format(prev_commit, item.commit.hexsha),
                    name_only=True).split()
            changed_files.update(diff_files)
            prev_commit = item.commit.hexsha
    except (InvalidGitRepositoryError, NoSuchPathError) as e:
        logger.info("Local repository {} not found, cloning from remote".\
                    format(local_repo_path))
        try:
            remote_repo = Repo(remote_repo_path)
        except NoSuchPathError as e:
            raise ConfigException("Invalid remote repository {}: {}".format(
                remote_repo_path,
                str(e)
            ))

        remote_repo.clone(local_repo_path)
        local_repo = Repo(local_repo_path)
        ret = 'Cloned new from remote. Last commit {} by {} at {}'.format(
            local_repo.head.commit.name_rev,
            local_repo.head.commit.committer,
            local_repo.head.commit.committed_datetime
        )

    if repo_type == RepoType.SETTINGS:
        try:
            get_settings()
        except SettingsSyntaxError as e:
            logger.exception("Error in settings repo configuration: {}".format(str(e)))
            raise e
        logger.debug("Files changed in settings repository: {}".format(changed_files))
        updated_devtypes = settings_syncstatus(updated_settings=changed_files)
        logger.debug("Devicestypes to be marked unsynced after repo refresh: {}".
                     format(', '.join([dt.name for dt in updated_devtypes])))
        with sqla_session() as session:
            devtype: DeviceType
            for devtype in updated_devtypes:
                Device.set_devtype_syncstatus(session, devtype, syncstatus=False)

    if repo_type == RepoType.TEMPLATES:
        logger.debug("Files changed in template repository: {}".format(changed_files))
        updated_devtypes = template_syncstatus(updated_templates=changed_files)
        logger.debug("Devicestypes to be marked unsynced after repo refresh: {}".
                     format(', '.join([dt.name for dt in updated_devtypes])))
        with sqla_session() as session:
            devtype: DeviceType
            for devtype, platform in updated_devtypes:
                Device.set_devtype_syncstatus(session, devtype, platform, syncstatus=False)

    return ret


def template_syncstatus(updated_templates: set) -> Set[Tuple[DeviceType, str]]:
    """Determine what device types have become unsynchronized because
    of updated template files."""
    unsynced_devtypes = set()
    with open('/etc/cnaas-nms/repository.yml', 'r') as db_file:
        repo_config = yaml.safe_load(db_file)
        local_repo_path = repo_config['templates_local']

    # loop through OS/platform types
    for platform in os.listdir(local_repo_path):
        path = os.path.join(local_repo_path, platform)
        if not os.path.isdir(path) or platform.startswith('.'):
            continue

        mapfile = os.path.join(path, 'mapping.yml')
        if not os.path.isfile(mapfile):
            raise RepoStructureException(
                "File mapping.yml not found in template repo {}".format(path))
        try:
            with open(mapfile, 'r') as f:
                mapping = yaml.safe_load(f)
        except Exception as e:
            logger.exception(
                "Could not parse {}/mapping.yml in template repo: {}".format(path, str(e)))
            raise RepoStructureException(
                "Could not parse {}/mapping.yml in template repo: {}".format(path, str(e)))

        devtype: DeviceType
        for devtype in DeviceType:
            if devtype.name in mapping:
                update_required = False
                try:
                    dependencies = list([mapping[devtype.name]['entrypoint']])
                    if 'dependencies' in mapping[devtype.name] and \
                            isinstance(mapping[devtype.name]['dependencies'], list):
                        dependencies.extend(mapping[devtype.name]['dependencies'])
                except KeyError as e:
                    logger.exception(
                        "Could not parse mapping.yml in template repo for {}, value not found: {}".
                        format(devtype.name, str(e)))
                    raise RepoStructureException(
                        "Could not parse mapping.yml in template repo for {}, value not found: {}".
                        format(devtype.name, str(e)))

                for dependency in dependencies:
                    if os.path.join(platform, dependency) in updated_templates:
                        update_required = True
                if update_required:
                    logger.info("Template for device type {} has been updated".
                                format(devtype.name))
                    unsynced_devtypes.add((devtype, platform))

    return unsynced_devtypes


def settings_syncstatus(updated_settings: set) -> Set[DeviceType]:
    """Determine what devices has become unsynchronized after updating
    the settings repository."""
    unsynced_devtypes = set()
    filename: str
    for filename in updated_settings:
        basedir = filename.split(os.path.sep)[0]
        if basedir not in DIR_STRUCTURE:
            continue
        if basedir.startswith('global'):
            return {DeviceType.ACCESS, DeviceType.DIST, DeviceType.CORE}
        elif basedir.startswith('fabric'):
            unsynced_devtypes.update({DeviceType.DIST, DeviceType.CORE})
        elif basedir.startswith('access'):
            unsynced_devtypes.add(DeviceType.ACCESS)
        elif basedir.startswith('dist'):
            unsynced_devtypes.add(DeviceType.DIST)
        elif basedir.startswith('core'):
            unsynced_devtypes.add(DeviceType.CORE)
        else:
            logger.warn("Unhandled settings file found {}, syncstatus not updated".
                        format(filename))
    return unsynced_devtypes
