""" Driver for AMQP support """

import inspect
import pickle
import time

import pendulum

from config import queue
from masonite.contracts import QueueContract
from masonite.drivers import BaseQueueDriver
from masonite.exceptions import DriverLibraryNotFound
from masonite.helpers import HasColoredCommands
from masonite.queues import Queueable

if 'amqp' in queue.DRIVERS:
    listening_channel = queue.DRIVERS['amqp']['channel']
else:
    listening_channel = 'default'


class QueueAmqpDriver(BaseQueueDriver, QueueContract, HasColoredCommands):

    def __init__(self):
        """Queue AMQP Driver
        """

        # Start the connection
        self.publishing_channel = listening_channel
        self.connect()

    def _publish(self, body):

        self.channel.basic_publish(exchange='',
                                   routing_key=self.publishing_channel,
                                   body=pickle.dumps(
                                       body
                                   ),
                                   properties=self.pika.BasicProperties(
                                       delivery_mode=2,  # make message persistent
                                   ))

    def push(self, *objects, args=(), callback='handle', ran=1, channel=None):
        """Push objects onto the amqp stack.

        Arguments:
            objects {*args of objects} - This can be several objects as parameters into this method.
        """
        if channel:
            self.publishing_channel = channel

        for obj in objects:
            # Publish to the channel for each object
            payload = {'obj': obj, 'args': args, 'callback': callback, 'created': pendulum.now(), 'ran': ran}
            try:
                self._publish(payload)
            except self.pika.exceptions.ConnectionClosed:
                self.connect()
                self._publish(payload)

    def connect(self):
        try:
            import pika
            self.pika = pika
        except ImportError:
            raise DriverLibraryNotFound(
                "Could not find the 'pika' library. Run pip install pika to fix this.")

        self.connection = pika.BlockingConnection(pika.URLParameters('amqp://{}:{}@{}{}/{}'.format(
            queue.DRIVERS['amqp']['username'],
            queue.DRIVERS['amqp']['password'],
            queue.DRIVERS['amqp']['host'],
            ':' + str(queue.DRIVERS['amqp']['port']) if 'port' in queue.DRIVERS['amqp'] and queue.DRIVERS['amqp']['port'] else '',
            queue.DRIVERS['amqp']['vhost'] if 'vhost' in queue.DRIVERS['amqp'] and queue.DRIVERS['amqp']['vhost'] else '%2F'
        )))

        self.channel = self.connection.channel()

        self.channel.queue_declare(queue=self.publishing_channel, durable=True)

        return self

    def consume(self, channel, fair=False):
        self.success('[*] Waiting to process jobs on the "{}" channel. To exit press CTRL+C'.format(
            channel))

        self.channel.basic_consume(self.work,
                                   queue=channel)

        if fair:
            self.channel.basic_qos(prefetch_count=1)
        return self.channel.start_consuming()

    def work(self, ch, method, properties, body):
        from wsgi import container
        job = pickle.loads(body)
        obj = job['obj']
        args = job['args']
        callback = job['callback']
        ran = job['ran']

        try:
            try:
                if inspect.isclass(obj):
                    obj = container.resolve(obj)

                getattr(obj, callback)(*args)

            except AttributeError:
                obj(*args)

            self.success('[\u2713] Job Successfully Processed')
        except Exception as e:
            self.danger('Job Failed: {}'.format(str(e)))

            if ran < 3 and isinstance(obj, Queueable):
                time.sleep(1)
                self.push(obj.__class__, args=args, callback=callback, ran=ran + 1)
            else:
                if hasattr(obj, 'failed'):
                    getattr(obj, 'failed')(job, str(e))

                self.add_to_failed_queue_table(job)

        ch.basic_ack(delivery_tag=method.delivery_tag)
