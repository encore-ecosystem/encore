# ER-Nodes (Exclusively Reachable Nodes)

The EHIR abstract virtual machine uses a graph memory model: each object is represented as a node, and relationships between objects are represented as edges.

After the last interaction with an object, the VM performs cascading deallocation. "Cascading" means that not only the original object may be deallocated, but also some of its descendants. At the same time, an object may remain allocated if it is still reachable from another live object.

The set of nodes to deallocate is defined as follows.

Let $P(v)$ be the set of nodes reachable from $v$, and assume $v \in P(v)$ for all $v$.

Then:

$$ ERN(v) = P(v) - \bigcup_{k \in \overline{P(v)}} P(k) $$

or

$$ ERN(v) = P(v) - \bigcup_{k \in \overline{P(v)}} (P(k) \bigcap P(v)) $$
