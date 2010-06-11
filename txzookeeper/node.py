from zookeeper import NoNodeException, BadVersionException
from twisted.internet.defer import Deferred
from txzookeeper.client import ZOO_OPEN_ACL_UNSAFE


class ZNode(object):
    """
    A minimal object abstraction over a zookeeper node, utilizes no caching
    outside of trying to keep track of node existance and the last read
    version. It will attempt to utilize the last read version when modifying
    the node. On a bad version exception this values are cleared and the
    except reraised (errback chain continue.)
    """

    def __init__(self, path, context):
        self._path = path
        self._name = path.split("/")[-1]
        self._context = context
        self._node_stat = None

    @property
    def path(self):
        """
        The path to the node from the zookeeper root.
        """
        return self._path

    @property
    def name(self):
        """
        The name of the node in its container.
        """
        return self._name

    def _get_version(self):
        if not self._node_stat:
            return -1
        return self._node_stat["version"]

    def _on_error_bad_version(self, failure):
        failure.trap(BadVersionException)
        self._node_stat = None
        return failure

    def create(self, data="", acl=None, flags=0):
        """
        Create the node with the given data, acl, and persistence flags. If no
        acl is given the default public acl is used. The default creation flag
        is persistent.
        """
        if acl is None:
            acl = [ZOO_OPEN_ACL_UNSAFE]
        d = self._context.create(self.path, data, acl, flags)
        return d

    def _on_exists_success(self, node_stat):
        if node_stat is None:
            return False
        self._node_stat = node_stat
        return True

    def exists(self):
        """
        Does the node exist or not, returns a boolean.
        """
        d = self._context.exists(self.path)
        d.addCallback(self._on_exists_success)
        return d

    def exists_and_watch(self):
        """
        Returns a boolean based on the node's existence. Also returns a
        deferred that fires when the node is modified/created/added/deleted.
        """
        node_changed = Deferred()

        def on_node_event(event, state, path):
            return node_changed.callback((event, state, path))

        d = self._context.exists(self.path, on_node_event)
        d.addCallback(self._on_exists_success)
        return d, node_changed

    def _on_get_node_error(self, failure):
        failure.trap(NoNodeException)
        self._node_stat = None
        return failure

    def _on_get_node_success(self, data):
        (node_data, node_stat) = data
        self._node_stat = node_stat
        return node_data

    def get_data(self):
        """Retrieve the node's data."""
        d = self._context.get(self.path)
        d.addCallback(self._on_get_node_success)
        d.addErrback(self._on_get_node_error)
        return d

    def get_data_and_watch(self):
        """
        Retrieve the node's data and a deferred that fires when this data
        changes.
        """
        node_changed = Deferred()

        def on_node_change(event, status, path):
            node_changed.callback((event, status, path))

        d = self._context.get(self.path, watcher=on_node_change)
        d.addCallback(self._on_get_node_success)
        d.addErrback(self._on_get_node_error)
        return d, node_changed

    def set_data(self, data):
        """Set the node's data."""

        def on_success(value):
            self._node_stat = None
            return self

        version = self._get_version()
        d = self._context.set(self.path, data, version)
        d.addErrback(self._on_error_bad_version)
        d.addCallback(on_success)
        return d

    def get_acl(self):
        """
        Get the ACL for this node. An ACL is a list of access control
        entity dictionaries.
        """

        def on_success((acl, stat)):
            if stat is not None:
                self._node_stat = stat
            return acl
        d = self._context.get_acl(self.path)
        d.addCallback(on_success)
        return d

    def set_acl(self, acl):
        """
        Set the ACL for this node.
        """
        d = self._context.set_acl(
            self.path, acl, self._get_version())
        d.addErrback(self._on_error_bad_version)
        return d

    def _on_get_children_filter_results(self, children, prefix):
        if prefix:
            children = [
                name for name in children if name.startswith(prefix)]
        return [
            self.__class__("/".join((self.path, name)), self._context)
            for name in children]

    def get_children(self, prefix=None):
        """
        Get the children of this node, as ZNode objects. Optionally
        a name prefix may be passed which the child node must abide.
        """
        d = self._context.get_children(self.path)
        d.addCallback(self._on_get_children_filter_results, prefix)
        return d

    def get_children_and_watch(self, prefix=None):
        """
        Get the children of this node, as ZNode objects, and also return
        a deferred that fires if a child is added or deleted. Optionally
        a name prefix may be passed which the child node must abide.
        """
        children_changed = Deferred()

        def on_child_added_removed(event, status, path):
            # path is the container not the child.
            children_changed.callback((event, status, path))

        d = self._context.get_children(
            self.path, watcher=on_child_added_removed)
        d.addCallback(self._on_get_children_filter_results, prefix)
        return d, children_changed

    def __cmp__(self, other):
        return cmp(self.path, other.path)
