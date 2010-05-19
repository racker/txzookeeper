
from twisted.internet.defer import inlineCallbacks, returnValue, DeferredList

from txzookeeper import ZookeeperClient
from txzookeeper.queue import Queue, Empty
from txzookeeper.tests import ZookeeperTestCase, utils


class QueueTests(ZookeeperTestCase):

    def setUp(self):
        super(QueueTests, self).setUp()
        self.clients = []

    def tearDown(self):
        cleanup = False

        for client in self.clients:
            if not cleanup and client.connected:
                utils.deleteTree(handle=client.handle)
                cleanup = True
            if client.connected:
                client.close()
        super(QueueTests, self).tearDown()

    @inlineCallbacks
    def open_client(self, credentials=None):
        """
        Open a zookeeper client, optionally authenticating with the
        credentials if given.
        """
        client = ZookeeperClient("127.0.0.1:2181")
        self.clients.append(client)
        yield client.connect()
        if credentials:
            d = client.add_auth("digest", credentials)
            # hack to keep auth fast
            yield client.exists("/")
            yield d
        returnValue(client)

    @inlineCallbacks
    def test_put_get_nowait_item(self):
        """
        We can put and get an item off the queue.
        """
        client = yield self.open_client()
        path = yield client.create("/queue-test")
        queue = Queue(path, client)
        item = "transform image bluemarble.jpg"
        yield queue.put(item)
        item2 = yield queue.get_nowait()
        self.assertEqual(item, item2)

    @inlineCallbacks
    def test_get_nowait_empty_queue(self):
        """
        Fetching from an empty queue raises the Empty exception if
        the client uses the the nowait api.
        """
        client = yield self.open_client()
        path = yield client.create("/queue-test")
        queue = Queue(path, client)
        queue_get = queue.get()
        yield self.failUnlessFailure(queue_get, Empty)

    @inlineCallbacks
    def test_put_item(self):
        """
        An item can be put on the queue, and is stored in a node in
        queue's directory.
        """
        client = yield self.open_client()
        path = yield client.create("/queue-test")
        queue = Queue(path, client)
        item = "transform image bluemarble.jpg"
        yield queue.put(item)
        children = yield client.get_children(path)
        self.assertEqual(len(children), 1)
        data, stat = yield client.get("/".join((path, children[0])))
        self.assertEqual(data, item)

    @inlineCallbacks
    def test_get_with_wait(self):
        """
        Instead of getting an empty error, get can also be used
        that returns a deferred that only is called back when an
        item is ready in the queue.
        """
        client = yield self.open_client()
        test_client = yield self.open_client()

        path = yield client.create("/queue-wait-test")
        item = "zebra moon"
        queue = Queue(path, client)
        d = queue.get_wait()

        @inlineCallbacks
        def push_item():
            queue = Queue(path, test_client)
            yield queue.put("zebra moon")

        def verify_item_received(data):
            self.assertEqual(data, item)
            return data

        d.addCallback(verify_item_received)

        from twisted.internet import reactor
        reactor.callLater(0.4, push_item)

        data = yield d
        self.assertEqual(data, item)

    @inlineCallbacks
    def test_multiconsumer_multiproducer(self):
        test_client = yield self.open_client()
        path = yield test_client.create("/multi-prod-cons")

        consume_results = []
        produce_results = []

        @inlineCallbacks
        def producer(start, offset):
            client = yield self.open_client()
            q = Queue(path, client)
            for i in range(start, start+offset):
                yield q.put(str(i))
                produce_results.append(str(i))

        @inlineCallbacks
        def consumer(max):
            client = yield self.open_client()
            q = Queue(path, client)
            attempts = range(max)
            for el in attempts:
                try:
                    value = yield q.get()
                except Empty:
                    returnValue("")
                consume_results.append(value)
            returnValue(True)

        # two producers 20 items total
        yield DeferredList(
            [producer(0, 10), producer(10, 10)])

        children = yield test_client.get_children(path)
        self.assertEqual(len(children), 20)

        yield DeferredList(
            [consumer(10), consumer(10), consumer(10)])

        yield DeferredList(
            [consumer(5), consumer(5), consumer(5), consumer(6)])

        err = set(produce_results)-set(consume_results)
        self.assertFalse(err)
        self.assertEqual(len(consume_results), len(produce_results))
