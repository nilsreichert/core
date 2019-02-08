"""Base queue driver."""

import pickle
import pendulum

from masonite.helpers import HasColoredCommands
from masonite.drivers import BaseDriver
from config import queue

if 'amqp' in queue.DRIVERS:
    listening_channel = queue.DRIVERS['amqp']['channel']
else:
    listening_channel = 'default'

class BaseQueueDriver(BaseDriver, HasColoredCommands):

    def add_to_failed_queue_table(self, payload):
        from config.database import DB as schema
        if schema.get_schema_builder().has_table('failed_jobs'):
            schema.table('failed_jobs').insert({
                'driver': 'amqp',
                'channel': listening_channel,
                'payload': pickle.dumps(payload),
                'failed_at': pendulum.now()
            })

    def run_failed_jobs(self):
        from config.database import DB as schema
        try:
            self.success('Attempting to send failed jobs back to the queue ...')
            for job in schema.table('failed_jobs').get():
                payload = pickle.loads(job.payload)
                schema.table('failed_jobs').where('payload', job.payload).delete()
                self.push(payload['obj'], args=payload['args'], callback=payload['callback'])
        except Exception:
            self.danger('Could not get the failed_jobs table')

    def push(self, *objects, args=(), callback='handle', ran=1, channel=None):
        raise NotImplementedError
