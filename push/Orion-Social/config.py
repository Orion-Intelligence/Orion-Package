import shutil

SLUG = 'social'
PORT = 8020
MODULE = 'api.server:app'
PROJECT = 'trusted-social'
COMPOSE = 'docker-compose.yml'
REQUIRED_ENV = ('TOR_PASSWORD',)
RELEASE = 'ENV ORION_SOCIAL_SESSIONS_DIR=/app/sessions\n'


def configure(config):
    config['services']['api']['environment']['ORION_SOCIAL_SESSIONS_DIR'] = '/app/sessions'
    config.get('volumes', {}).pop('social_automation_node_modules', None)


def prepare(context, repo, ignored, run):
    automation = context / 'app/social-automation'
    shutil.copytree(repo / 'social-automation/src', automation / 'src', ignore=ignored)
    for filename in ('package.json', 'package-lock.json'):
        shutil.copy2(repo / 'social-automation' / filename, automation / filename)
