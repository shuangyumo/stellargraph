# -*- coding: utf-8 -*-
#
# Copyright 2018 Data61, CSIRO
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Graph node classification using GraphSAGE.
This currently is only tested on the CORA dataset, which can be downloaded from https://linqs-data.soe.ucsc.edu/public/lbc/cora.tgz

The following is the description of the dataset:
> The Cora dataset consists of 2708 scientific publications classified into one of seven classes.
> The citation network consists of 5429 links. Each publication in the dataset is described by a
> 0/1-valued word vector indicating the absence/presence of the corresponding word from the dictionary.
> The dictionary consists of 1433 unique words. The README file in the dataset provides more details.

Download and unzip the cora.tgz file to a location on your computer and pass this location
as a command line argument to this script:

E.G. Assuming the CORA dataset is here:
```
    ~/data/cora
```
and contains cora.cites and cora.content.

Run this script as follows:
```
    python epgm-example.py -g ~/data/cora
```
"""
import os
import argparse
import pickle
import numpy as np
import pandas as pd
import networkx as nx
import keras
from keras import optimizers, losses, layers, metrics
from sklearn import preprocessing, feature_extraction, model_selection
from stellargraph import StellarGraph
from stellargraph.layer.graphsage import GraphSAGE, MeanAggregator
from stellargraph.mapper.node_mappers import GraphSAGENodeMapper


def train(
    edgelist,
    node_data,
    layer_size,
    num_samples,
    batch_size=100,
    num_epochs=10,
    learning_rate=0.005,
    dropout=0.0,
    target_name="subject",
):
    """
    Train a GraphSAGE model on the specified graph G with given parameters.

    Args:
        edgelist: Graph edgelist
        node_data: Feature and target data for nodes
        layer_size: A list of number of hidden nodes in each layer
        num_samples: Number of neighbours to sample at each layer
        batch_size: Size of batch for inference
        num_epochs: Number of epochs to train the model
        learning_rate: Initial Learning rate
        dropout: The dropout (0->1)
    """
    # Extract target and encode as a one-hot vector
    target_encoding = feature_extraction.DictVectorizer(sparse=False)
    node_targets = target_encoding.fit_transform(
        node_data[[target_name]].to_dict("records")
    )

    # Extract the feature data. These are the feature vectors that the Keras model will use as input.
    # The CORA dataset contains attributes 'w_x' that correspond to words found in that publication.
    node_features = node_data[feature_names].values
    node_ids = node_data.index

    # Create graph from edgelist and set node features and node type
    Gnx = nx.from_pandas_edgelist(edgelist)
    for nid, f in zip(node_data.index, node_features):
        Gnx.node[nid]["feature"] = f
        Gnx.node[nid]["label"] = "paper"

    # Convert to StellarGraph and prepare for ML
    G = StellarGraph(Gnx)
    G.fit_attribute_spec()

    # Split nodes into train/test using stratification.
    train_nodes, test_nodes, train_targets, test_targets = model_selection.train_test_split(
        node_ids, node_targets, train_size=140, test_size=None, stratify=node_targets
    )

    # Split test set into test and validation
    val_nodes, test_nodes, val_targets, test_targets = model_selection.train_test_split(
        test_nodes, test_targets, train_size=500, test_size=None
    )

    # Create mappers for GraphSAGE that input data from the graph to the model
    train_mapper = GraphSAGENodeMapper(
        G, train_nodes, batch_size, num_samples, targets=train_targets
    )
    val_mapper = GraphSAGENodeMapper(
        G, val_nodes, batch_size, num_samples, targets=val_targets
    )

    # GraphSAGE model
    model = GraphSAGE(
        layer_sizes=layer_size, mapper=train_mapper, bias=True, dropout=dropout
    )
    x_inp, x_out = model.default_model(flatten_output=True)

    # Final estimator layer
    prediction = layers.Dense(units=train_targets.shape[1], activation="softmax")(x_out)

    # Create Keras model for training
    model = keras.Model(inputs=x_inp, outputs=prediction)
    model.compile(
        optimizer=optimizers.Adam(lr=learning_rate),
        loss=losses.categorical_crossentropy,
        metrics=[metrics.categorical_accuracy],
    )

    # Train model
    history = model.fit_generator(
        train_mapper,
        epochs=num_epochs,
        validation_data=val_mapper,
        verbose=2,
        shuffle=True,
    )

    # Evaluate on test set and print metrics
    test_mapper = GraphSAGENodeMapper(
        G, test_nodes, batch_size, num_samples, targets=test_targets
    )
    test_metrics = model.evaluate_generator(test_mapper)
    print("\nTest Set Metrics:")
    for name, val in zip(model.metrics_names, test_metrics):
        print("\t{}: {:0.4f}".format(name, val))

    # Get predictions for all nodes
    all_mapper = GraphSAGENodeMapper(G, node_ids, batch_size, num_samples)
    all_predictions = model.predict_generator(all_mapper)

    # Turn predictions back into the original categories
    node_predictions = pd.DataFrame(
        target_encoding.inverse_transform(all_predictions), index=node_ids
    )
    accuracy = np.mean(
        [
            "subject=" + gt_subject == p
            for gt_subject, p in zip(
                node_data["subject"], node_predictions.idxmax(axis=1)
            )
        ]
    )
    print("All-node accuracy: {:3f}".format(accuracy))

    # TODO: extract the GraphSAGE embeddings from x_out, and save/plot them

    # Save the trained model
    save_str = "_n{}_l{}_d{}_r{}".format(
        "_".join([str(x) for x in num_samples]),
        "_".join([str(x) for x in layer_size]),
        dropout,
        learning_rate,
    )
    model.save("epgm_example_model" + save_str + ".h5")

    # We must also save the target encoding to convert model predictions
    with open("epgm_example_encoding" + save_str + ".pkl", "wb") as f:
        pickle.dump([target_encoding], f)


def test(G, model_file, batch_size):
    """
    Load the serialized model and evaluate on all nodes in the graph.

    Args:
        G: NetworkX graph file
        target_converter: Class to give numeric representations of node targets
        feature_converter: CLass to give numeric representations of the node features
        model_file: Location of Keras model to load
        batch_size: Size of batch for inference
    """
    # TODO: This needs to be written
    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Graph node classification using GraphSAGE"
    )
    parser.add_argument(
        "-c",
        "--checkpoint",
        nargs="?",
        type=str,
        default=None,
        help="Load a saved checkpoint file",
    )
    parser.add_argument(
        "-n", "--batch_size", type=int, default=20, help="Batch size for training"
    )
    parser.add_argument(
        "-e",
        "--epochs",
        type=int,
        default=10,
        help="The number of epochs to train the model",
    )
    parser.add_argument(
        "-d",
        "--dropout",
        type=float,
        default=0.0,
        help="Dropout for the GraphSAGE model, between 0.0 and 1.0",
    )
    parser.add_argument(
        "-r",
        "--learningrate",
        type=float,
        default=0.005,
        help="Learning rate for training model",
    )
    parser.add_argument(
        "-s",
        "--neighbour_samples",
        type=int,
        nargs="*",
        default=[20, 10],
        help="The number of nodes sampled at each layer",
    )
    parser.add_argument(
        "-l",
        "--layer_size",
        type=int,
        nargs="*",
        default=[20, 20],
        help="The number of hidden features at each layer",
    )
    parser.add_argument(
        "-g", "--graph", type=str, default=None, help="The graph stored in EPGM format."
    )
    parser.add_argument(
        "-t",
        "--target",
        type=str,
        default="subject",
        help="The target node attribute (categorical)",
    )
    args, cmdline_args = parser.parse_known_args()

    # Load graph edgelist
    graph_loc = os.path.expanduser(args.graph)
    edgelist = pd.read_table(
        os.path.join(graph_loc, "cora.cites"), header=None, names=["source", "target"]
    )

    # Load node features
    feature_names = ["w_{}".format(ii) for ii in range(1433)]
    column_names = feature_names + ["subject"]
    node_data = pd.read_table(
        os.path.join(graph_loc, "cora.content"), header=None, names=column_names
    )

    if args.checkpoint is None:
        train(
            edgelist,
            node_data,
            args.layer_size,
            args.neighbour_samples,
            args.batch_size,
            args.epochs,
            args.learningrate,
            args.dropout,
        )
    else:
        test(G, args.checkpoint, args.batch_size)
