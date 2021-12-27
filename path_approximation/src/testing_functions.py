import logging
import os.path
from datetime import datetime

import numpy as np
import torch.cuda
from imblearn.over_sampling import RandomOverSampler
from imblearn.under_sampling import RandomUnderSampler
from sklearn.metrics import accuracy_score, mean_absolute_error, mean_squared_error, mean_absolute_percentage_error
from torch import tensor, reshape
import dgl
import osmnx as ox

import models
from datasets_generator import create_train_val_test_sets
import data_helper
from routing import GraphRouter
from Trainer import Trainer


def get_test_result(config, file_name, portion, seed, model):
    """
    test model on random selected pair of nodes from the graph

    :param: file_name working data graph
    :param: portion, the portion of test data out of total data
    :seed: random seed

    :return x_test,y_test

    """
    device = "cuda" if torch.cuda.is_available() else "cpu"

    config["dataset"]["sample_ratio"] = portion
    config["dataset"]["sample_method"] = "random"
    config["random_seed"] = seed
    config["graph"]["name"] = file_name

    data = create_train_val_test_sets(config)
    x, y = tensor(data['x_train'].astype(np.float32)), tensor(
        data['y_train'].astype(np.float32))  # just for convenience, that's for test not for train
    pred = model(x.to(device)).reshape(-1)  # use model to predict
    y = y.detach().numpy()
    pred = pred.detach().numpy()
    return accuracy_score(np.round(pred), y), mean_absolute_error(pred, y), mean_squared_error(pred,
                                                                                               y), mean_absolute_percentage_error(
        pred, y)


def round_num(scores):
    """
    round all the scores number 
    
    return a dictionary 
    """
    for score in scores:
        scores[score] = str(round(scores[score], 4))
    return scores


#####################


def run_nn(config):
    """
    Run Neural Network Model
    :param config: provide all we need in terms of parameters
    :param force_recreate_datasets:
    :param write_train_val_test:
    :return: a neural net model
    """

    now = datetime.now()

    logging.basicConfig(filename=os.path.join(config["log_path"], "running_log.log"), level=logging.INFO)
    datasets = create_train_val_test_sets(config=config)

    file_name = config["graph"]["name"]
    portion = config["dataset"]["sample_ratio"]
    method = config["dataset"]["sample_method"]

    model = models.run_neural_net(datasets, file_name)
    logging.info("run nn on " + file_name + " at " + now.strftime("%m/%d/%Y %H:%M:%S ") + "{}%".format(
        float(portion) * 100) + " " + method)
    acc, mae, mse, mre = get_test_result(config, file_name, 0.14, 824,
                                         model)  # for small graph, we can have large portion of data to test, but for large graph
    # chose smaller portion to save time
    logging.info("ACC " + str(round(acc, 4) * 100) + "%" + " ||| " + "MAE: " + str(round(mae, 4)))
    logging.info("MSE " + str(round(mse, 4)) + " ||| " + "MRE: " + str(round(mre, 4)))
    logging.info("------------------------")
    return model


def run_some_linear_models(config, force_recreate_datasets, write_train_val_test):
    """
    Testing purpose.
    :param file_name:
    :return:
    """
    log_path = config["log_path"]
    logging.basicConfig(filename=os.path.join(log_path, "running_log.log"), level=logging.INFO)

    datasets = create_train_val_test_sets(config=config, force_recreate_datasets=force_recreate_datasets,
                                          write_train_val_test=write_train_val_test)

    ##### run some linear regression models
    scores = models.run_linear_regression(datasets, use_standard_scaler=True, merge_train_val=False)

    logging.info("run_some_linear_models_test!")
    logging.info(scores)

    return True


def run_linear_model_with_under_and_over_sampling(file_name, force_recreate_datasets, write_train_val_test,
                                                  logs_path="logs", seed_random=9999):
    """
    Try to do under and over-sampling on training set before feeding through a linear regresison model
    :param file_name:
    :param force_recreate_datasets:
    :param write_train_val_test:
    :param seed_random:
    :return:
    """
    logging.basicConfig(filename=f'../output/{logs_path}/running_log.log', level=logging.INFO)

    datasets = create_train_val_test_sets(file_name, force_recreate_datasets=force_recreate_datasets,
                                          write_train_val_test=write_train_val_test)

    x_train, y_train = datasets["x_train"], datasets["y_train"]
    values, counts = np.unique(y_train, return_counts=True)

    x = int(counts[2] * 0.7)
    y = int(0.7 * x)

    ## Undersampling
    undersample_dict = {2: y, 3: x}
    under_sampler = RandomUnderSampler(sampling_strategy=undersample_dict, random_state=seed_random)  # n_jobs=15,
    x_train, y_train = under_sampler.fit_resample(x_train, y_train.astype(np.int))
    print('Frequency of distance values after undersampling', np.unique(y_train, return_counts=True))

    ## Oversampling
    minority_samples = int(0.7 * x)
    oversample_dict = {1: minority_samples, 4: minority_samples, 5: minority_samples, 6: minority_samples,
                       7: minority_samples}
    over_sampler = RandomOverSampler(sampling_strategy=oversample_dict,
                                     random_state=seed_random)
    x_train, y_train = over_sampler.fit_resample(x_train, y_train.astype(np.int))
    print('Frequency of distance values after oversampling', np.unique(y_train, return_counts=True))

    datasets["x_train"], datasets["y_train"] = x_train, y_train
    scores = models.run_linear_regression(datasets, use_standard_scaler=True, merge_train_val=False)

    logging.info(run_linear_model_with_under_and_over_sampling)
    logging.info(scores)

    return True

def run_astar(pairs):
        sum_visited = 0
        curr_time = datetime.now()
        for i, p in enumerate(pairs):
            if i % 10 == 0:
                print(i)
            u, v = p
            _, num_visited, _ = gr.astar(u, v)
            sum_visited += num_visited
        print(datetime.now() - curr_time)
        print(sum_visited / len(pairs))

def plot_route(gr, f_name, node_to_idx, u, v):
    G = gr.graph

    route, _, visited = gr.astar(u, v, weight="length")
    path_length = 0
    for i in range(1, len(route)):
        path_length += G.edges[route[i-1], route[i], 0]['length']
    print()
    print("path length:", path_length)
    print()
    visited = set(visited)

    node_colors = [(1, 1, 1) for _ in range(G.number_of_nodes())]

    m = len(visited) // 6
    r, g, b = m, 0, 0
    updates = [(0,1,0),(-1,0,0),(0,0,1),(0,-1,0),(1,0,0),(0,0,-1)]
    for i,n in enumerate(visited):
        j = int((i / m) % 6)
        r, g, b = r + updates[j][0], g + updates[j][1], b + updates[j][2]
        node_colors[node_to_idx[n]] = (r/m, g/m, b/m)

    fig, ax = ox.plot.plot_graph(G, node_color=node_colors)
    fig, ax = ox.plot.plot_graph_route(G, route, route_color='black', ax=ax)
    fig.savefig(f_name)

def run_routing(config, nx_graph, embedding, model):
    """
    Run routing algorithm on given graph with given heuristic and landmark method
    :param config: provide all we need in terms of parameters
    :return: ?
    """
    node_to_idx = {v: i for i,v in enumerate(list(nx_graph.nodes()))}
    def dot_heuristic(x,y):
        d = np.sigmoid(np.dot(embedding[node_to_idx[x]], embedding[node_to_idx[y]]))
        if d == 0:
            return 0
        D = config["node2vec"]["init_c"]*(1-d)/d
        return D

    def model_heuristic(x, y):
        input = np.array((embedding[x] + embedding[y]) / 2.0).reshape(1,-1)
        return Trainer.predict(model, input)[0]

    def dist_heuristic(a, b):
        R = 6731000
        p = np.pi/180
        lat_a, long_a, lat_b, long_b = nx_graph.nodes[a]['y'], nx_graph.nodes[a]['x'], nx_graph.nodes[b]['y'], nx_graph.nodes[b]['x'],
        
        d = 0.5 - np.cos((lat_b-lat_a)*p)/2 + np.cos(lat_a*p)*np.cos(lat_b*p) * (1-np.cos((long_b-long_a)*p))/2
        return 2*R*np.arcsin(np.sqrt(d))

    gr = GraphRouter(graph=nx_graph)
    pairs = [(np.random.choice(list(nx_graph.nodes())), np.random.choice(list(nx_graph.nodes()))) for i in range(config["routing_num_samples"])]
    u, v = np.random.choice(list(nx_graph.nodes())), np.random.choice(list(nx_graph.nodes()))
    if gr.graph.nodes[u]['y'] < gr.graph.nodes[v]['y']:
        u, v = v, u

    file_name = data_helper.get_file_name(config)
    plot_path = config["graph"]["plot_path"].format(name=file_name,
                                                    epochs=config["node2vec"]["epochs"],
                                                    lr=config["node2vec"]["lr"],
                                                    init_c=config["node2vec"]["init_c"])
    print("Dijkstra's")
    run_astar(pairs)
    plot_route(gr, plot_path+"/dijkstra.png", node_to_idx, u, v)

    # Load embeddings and distance measure. Generate heuristic function
    print("A* with DL heuristic")
    gr.distances = {}
    if config["node2vec"]["modified"]:
        gr.heuristic = dot_heuristic
    else:
        gr.heuristic = model_heuristic
    run_astar(pairs)
    plot_route(gr, plot_path+"/A*_dl.png", node_to_idx, u, v)

    if config["graph"]["source"] == "gr" or config["graph"]["source"] == "osmnx":
        gr.distances = {}
        gr.heuristic = dist_heuristic
        run_astar(pairs)
        plot_route(gr, plot_path+"/A*_dist.png", node_to_idx, u, v)