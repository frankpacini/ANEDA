import time
from collections import namedtuple

import numpy as np
import torch
import torch.nn as nn
from dgl.sampling import node2vec_random_walk
from sklearn.linear_model import LogisticRegression
from torch.utils.data import DataLoader

from data_helper import write_file


# https://github.com/dmlc/dgl/tree/e667545da55017d5dbbd3f243d986506284d3e41/examples/pytorch/node2vec
class Node2vec(nn.Module):
    """Node2vec model from paper path_approximation: Scalable Feature Learning for Networks <https://arxiv.org/abs/1607.00653>
    Attributes
    ----------
    g: DGLGraph
        The graph.
    embedding_dim: int
        Dimension of node embedding.
    walk_length: int
        Length of each trace.
    p: float
        Likelihood of immediately revisiting a node in the walk.  Same notation as in the paper.
    q: float
        Control parameter to interpolate between breadth-first strategy and depth-first strategy.
        Same notation as in the paper.
    num_walks: int
        Number of random walks for each node. Default: 10.
    window_size: int
        Maximum distance between the center node and predicted node. Default: 5.
    num_negatives: int
        The number of negative samples for each positive sample.  Default: 5.
    use_sparse: bool
        If set to True, use PyTorch's sparse embedding and optimizer. Default: ``True``.
    weight_name : str, optional
        The name of the edge feature tensor on the graph storing the (unnormalized)
        probabilities associated with each edge for choosing the next node.
        The feature tensor must be non-negative and the sum of the probabilities
        must be positive for the outbound edges of all nodes (although they don't have
        to sum up to one).  The result will be undefined otherwise.
        If omitted, DGL assumes that the neighbors are picked uniformly.
    dist_measure : func, optional
        The inverse measure of distance to use for the label of positive examples
        which is applied on the distance d in the graph between two nodes in a walk. 
        Should be a decreasing function with domain [0, +inf) and range [0, 1). 
        Examples include c/(c+d) for c > 0 and c^(-d) for c > 1.
    """

    def __init__(self, g, embedding_dim, walk_length, p, q, num_walks=10, window_size=5, num_negatives=5,
                 use_sparse=True, weight_name=None, init_c=10):
        super(Node2vec, self).__init__()

        assert walk_length >= window_size

        self.g = g
        self.embedding_dim = embedding_dim
        self.walk_length = walk_length
        self.p = p
        self.q = q
        self.num_walks = num_walks
        self.window_size = window_size
        self.num_negatives = num_negatives
        self.N = self.g.num_nodes()
        if weight_name is not None:
            self.prob = weight_name
        else:
            self.prob = None

        self.embedding = nn.Embedding(self.N+1, embedding_dim, sparse=use_sparse)

        #if use_sparse:
        #    c = torch.sparse_coo_tensor([[0]], float(init_c))
        #else:
        self.c = torch.tensor(float(init_c))
        #self.register_parameter(name="c", param=torch.nn.Parameter(c))

    def reset_parameters(self):
        self.embedding.reset_parameters()

    def sample(self, batch):
        """
        Generate positive and negative samples.
        Positive samples are generated from random walk
        Negative samples are generated from random sampling
        """
        if not isinstance(batch, torch.Tensor):
            batch = torch.tensor(batch)

        batch = batch.repeat(self.num_walks)
        # positive
        pos_traces, edge_ids = node2vec_random_walk(self.g, batch, self.p, self.q, self.walk_length, self.prob, return_eids=True)
        # print(pos_traces[0], edge_ids[0])

        # Query the list of edge weights, using the edge ids from the random walks as indices
        pos_dists = self.g.edata['length'][edge_ids.long().view(-1)].view(-1, self.walk_length)
        # # Pad with distance between starting node and itself for unfolding
        # pos_dists = torch.cat((torch.zeros(len(batch), 1), pos_dists), 1)

        # Perform rolling window on both node trace and corresponding edge distances
        pos_traces = pos_traces.unfold(1, self.window_size, 1)  # rolling window
        pos_traces = pos_traces.contiguous().view(-1, self.window_size)
        pos_dists = pos_dists.unfold(1, self.window_size-1, 1)
        pos_dists = pos_dists.contiguous().view(-1, self.window_size-1)

        # negative
        neg_batch = batch.repeat(self.num_negatives)
        neg_traces = torch.randint(self.N, (neg_batch.size(0), self.walk_length))
        neg_traces = torch.cat([neg_batch.view(-1, 1), neg_traces], dim=-1)
        neg_traces = neg_traces.unfold(1, self.window_size, 1)  # rolling window
        neg_traces = neg_traces.contiguous().view(-1, self.window_size)

        return pos_traces, pos_dists, neg_traces

    def forward(self, nodes=None):
        """
        Returns the embeddings of the input nodes
        Parameters
        ----------
        nodes: Tensor, optional
            Input nodes, if set `None`, will return all the node embedding.
        Returns
        -------
        Tensor
            Node embedding
        """

        emb = self.embedding.weight
        if nodes is None:
            return emb
        else:
            return emb[nodes]

    def loss(self, pos_trace, pos_dists, neg_trace):
        """
        Computes the loss given positive and negative random walks.
        Parameters
        ----------
        pos_trace: Tensor
            positive random walk trace
        neg_trace: Tensor
            negative random walk trace
        """
        e = 1e-15
        print(pos_trace[(pos_trace == -1).any(axis=1)])

        # Positive
        pos_start, pos_rest = pos_trace[:, 0], pos_trace[:, 1:].contiguous()  # start node and following trace
        w_start = self.embedding(pos_start).unsqueeze(dim=1)
        w_rest = self.embedding(pos_rest)
        pos_out = (w_start * w_rest).sum(dim=-1)
        # print(pos_trace[0], pos_rest[0], pos_out[0])

        # Negative
        neg_start, neg_rest = neg_trace[:, 0], neg_trace[:, 1:].contiguous()

        w_start = self.embedding(neg_start).unsqueeze(dim=1)
        w_rest = self.embedding(neg_rest)
        neg_out = (w_start * w_rest).sum(dim=-1)

        # compute loss
        # torch.Size([4480, 4])
        pos_loss = torch.pow(torch.sigmoid(pos_out) - torch.div(self.c, self.c + pos_dists), 2).mean()
        # neg_loss = torch.pow(neg_out, 2).mean()

        # pos_loss = -torch.log(torch.sigmoid(pos_out) + e).mean()
        neg_loss = -torch.log(1 - torch.sigmoid(neg_out) + e).mean()

        return pos_loss + neg_loss

    def loader(self, batch_size):
        """
        Parameters
        ----------
        batch_size: int
            batch size
        Returns
        -------
        DataLoader
            Node2vec training data loader
        """
        return DataLoader(torch.arange(self.N), batch_size=batch_size, shuffle=True, collate_fn=self.sample)

    @torch.no_grad()
    def evaluate(self, x_train, y_train, x_val, y_val):
        """
        Evaluate the quality of embedding vector via a downstream classification task with logistic regression.
        """
        x_train = self.forward(x_train)
        x_val = self.forward(x_val)

        x_train, y_train = x_train.cpu().numpy(), y_train.cpu().numpy()
        x_val, y_val = x_val.cpu().numpy(), y_val.cpu().numpy()
        lr = LogisticRegression(solver='lbfgs', multi_class='auto', max_iter=150).fit(x_train, y_train)

        return lr.score(x_val, y_val)


class Node2vecModel(object):
    """
    Wrapper of the ``Node2Vec`` class with a ``train`` method.
    Attributes
    ----------
    g: DGLGraph
        The graph.
    embedding_dim: int
        Dimension of node embedding.
    walk_length: int
        Length of each trace.
    p: float
        Likelihood of immediately revisiting a node in the walk.
    q: float
        Control parameter to interpolate between breadth-first strategy and depth-first strategy.
    num_walks: int
        Number of random walks for each node. Default: 10.
    window_size: int
        Maximum distance between the center node and predicted node. Default: 5.
    num_negatives: int
        The number of negative samples for each positive sample.  Default: 5.
    use_sparse: bool
        If set to True, uses PyTorch's sparse embedding and optimizer. Default: ``True``.
    weight_name : str, optional
        The name of the edge feature tensor on the graph storing the (unnormalized)
        probabilities associated with each edge for choosing the next node.
        The feature tensor must be non-negative and the sum of the probabilities
        must be positive for the outbound edges of all nodes (although they don't have
        to sum up to one).  The result will be undefined otherwise.
        If omitted, DGL assumes that the neighbors are picked uniformly. Default: ``None``.
    eval_set: list of tuples (Tensor, Tensor)
        [(nodes_train,y_train),(nodes_val,y_val)]
        If omitted, model will not be evaluated. Default: ``None``.
    eval_steps: int
        Interval steps of evaluation.
        if set <= 0, model will not be evaluated. Default: ``None``.
    device: str
        device, {'cpu', 'cuda'}, default 'cpu'
    """

    def __init__(self, g, embedding_dim, walk_length, p=1.0, q=1.0, num_walks=1, window_size=5,
                 num_negatives=5, use_sparse=True, weight_name=None, eval_set=None, eval_steps=-1, device='cpu', init_c=10):

        self.model = Node2vec(g, embedding_dim, walk_length, p, q, num_walks,
                              window_size, num_negatives, use_sparse, weight_name, init_c)
        self.g = g
        self.use_sparse = use_sparse
        self.eval_steps = eval_steps
        self.eval_set = eval_set

        if device == 'cpu':
            self.device = device
        else:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'

        print(f"...using {self.device}")

    def _train_step(self, model, loader, optimizer, device, c_optimizer=None):
        model.train()
        total_loss = 0
        for pos_traces, pos_dists, neg_traces in loader:
            pos_traces = pos_traces.to(device)
            pos_dists = pos_dists.to(device)
            neg_traces = neg_traces.to(device)
            optimizer.zero_grad()
            if c_optimizer:
                c_optimizer.zero_grad()
            loss = model.loss(pos_traces, pos_dists, neg_traces)
            loss.backward()
            optimizer.step()
            if c_optimizer:
                c_optimizer.step()
            total_loss += loss.item()
        return total_loss / len(loader)

    @torch.no_grad()
    def _evaluate_step(self):
        nodes_train, y_train = self.eval_set[0]
        nodes_val, y_val = self.eval_set[1]

        acc = self.model.evaluate(nodes_train, y_train, nodes_val, y_val)
        return acc

    def train(self, epochs, batch_size, learning_rate=0.01):
        """
        Parameters
        ----------
        epochs: int
            num of train epoch
        batch_size: int
            batch size
        learning_rate: float
            learning rate. Default 0.01.
        """
    
        self.model = self.model.to(self.device)
        loader = self.model.loader(batch_size)
        if self.use_sparse:
            params = list(self.model.parameters())
            optimizer = torch.optim.SparseAdam(params, lr=learning_rate)
            c_optimizer = None #torch.optim.Adam([params[0]], lr=learning_rate)
        else:
            optimizer = torch.optim.Adam(self.model.parameters(), lr=learning_rate)
            c_optimizer=None

        scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.995)
        for i in range(epochs):
            loss = self._train_step(self.model, loader, optimizer, self.device, c_optimizer)
            if self.eval_steps > 0:
                if epochs % self.eval_steps == 0:
                    if self.eval_set is not None:
                        acc = self._evaluate_step()
                        print("Epoch: {}, Train Loss: {:.4f}, Val Acc: {:.4f}".format(i + 1, loss, acc))
                    else:
                        print("Epoch: {}, Train Loss: {:.4f}".format(i + 1, loss))
                    # print("c: {}".format(self.model.c))
            scheduler.step()

    def embedding(self, nodes=None):
        """
        Returns the embeddings of the input nodes
        Parameters
        ----------
        nodes: Tensor, optional
            Input nodes, if set `None`, will return all the node embedding.
        Returns
        -------
        Tensor
            Node embedding.
        """

        return self.model(nodes)


def run_node2vec(graph, eval_set=None, args=None, output_path=None):
    t_tick = time.time()  ## start measuring running time
    if args is None:
        raise ValueError("need args for node2vec!")

    # Convert dict to tuple
    Node2VecParams = namedtuple('Node2VecParams', args)
    args = Node2VecParams(**args)

    # train Node2Vec
    print("training Node2Vec, it will take a while...")
    print("node2vec's arguments:", args)
    trainer = Node2vecModel(graph,
                            embedding_dim=args.embedding_dim,
                            walk_length=args.walk_length,
                            window_size=args.window_size,
                            p=args.p,
                            q=args.q,
                            num_walks=args.num_walks,
                            num_negatives=args.num_negatives,
                            init_c=args.init_c, #args.walk_length*graph.edata['length'].mean().item(),
                            eval_set=eval_set,
                            eval_steps=1,
                            device=args.device)

    trainer.train(epochs=args.epochs, batch_size=args.batch_size, learning_rate=args.lr)

    t_tock = time.time()

    print(f"done training node2vec, running time = {np.round((t_tock - t_tick) / 60)} minutes.")
    # Calc embedding
    embedding = trainer.embedding().data

    if args.device == "cuda":
        embedding = embedding.cpu().numpy()

    write_file(output_path, embedding)
    return embedding