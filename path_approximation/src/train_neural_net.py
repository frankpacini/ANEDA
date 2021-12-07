import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchsummary import summary

from neural_net.NeuralNet1 import NeuralNet1
from CustomDataset import CustomDataset
from data_helper import *
from evaluations import evaluate_metrics


def _make_train_step(model, loss_fn, optimizer):
    def train_step(x, y):
        model.train()
        yhat = model(x)
        loss = loss_fn(y, yhat)
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()
        return loss.item()

    return train_step


def _train_model(model, device, loss_fn, optimizer, lr_scheduler, n_epochs, train_loader, val_loader, verbose):
    train_step = _make_train_step(model, loss_fn, optimizer)

    training_losses = []
    validation_losses = []

    for epoch in range(n_epochs):
        batch_losses = []
        for x_batch, y_batch in train_loader:
            x_batch = x_batch.to(device)
            y_batch = y_batch.to(device)
            loss = train_step(x_batch, y_batch)
            batch_losses.append(loss)
        training_loss = np.mean(batch_losses)
        training_losses.append(training_loss)

        validation_loss, val_metrics = evaluate_model(model, loss_fn, val_loader, device, evaluate_metrics)
        validation_losses.append(validation_loss)
        if verbose:
            print(
                f"[epoch {epoch + 1}/{n_epochs}] Training loss: {training_loss:.4f};\tValidation loss: {validation_loss:.4f}, Validation metrics: {val_metrics}")
        if lr_scheduler:  # if we use learning rate scheduler
            lr_scheduler.step()  # update learning rate after each epoch
    print("Done Training.")

    return val_metrics


def evaluate_model(model, loss_fn, val_loader, device, evaluate_function=None):
    yhat_list = []
    ytrue_list = []
    val_losses = []
    with torch.no_grad():
        for x_val, y_val in val_loader:
            x_val = x_val.to(device)
            y_val = y_val.to(device)
            model.eval()
            yhat = model(x_val)

            val_loss = loss_fn(y_val, yhat).item()
            val_losses.append(val_loss)

            if evaluate_function:
                if device != "cpu":
                    yhat_list.append(yhat.cpu.numpy())
                    ytrue_list.append(y_val.cpu.numpy())
                else:
                    yhat_list.append(yhat)
                    ytrue_list.append(y_val)

        validation_loss = np.mean(val_losses)
    if evaluate_function:
        metric_scores = evaluate_function(np.vstack(ytrue_list), np.vstack(yhat_list), print_out=False)
    return validation_loss, metric_scores


def predict():
    ## TODO
    pass


def train_neural_net(dataset):
    """
    train a neural network
    :param dataset:
    :return:
    """

    train_dataset = CustomDataset(dataset["x_train"], dataset["y_train"])
    val_dataset = CustomDataset(dataset["x_val"], dataset["y_val"])

    train_loader = DataLoader(dataset=train_dataset, batch_size=500)
    val_loader = DataLoader(dataset=val_dataset, batch_size=500)

    params = read_yaml("../configs/neural_net.yaml")
    device = 'cuda' if torch.cuda.is_available() else 'cpu'

    model = NeuralNet1(params).to(device)
    epochs = 10
    lr = 0.001
    # optimizer = optim.Adam(model.parameters(), lr=lr)

    optimizer = torch.optim.RMSprop(model.parameters(), lr=params['lr'], alpha=0.99, eps=1e-08, weight_decay=0,
                                    momentum=0, centered=False)
    # loss_fn = nn.MSELoss()
    loss_fn = nn.PoissonNLLLoss(log_input=False, eps=1e-07, reduction='mean')

    lr_scheduler = torch.optim.lr_scheduler.CyclicLR(optimizer, params['min_lr'], params['max_lr'],
                                                     step_size_up=8 * len(train_dataset), step_size_down=None,
                                                     mode=params['lr_sched_mode'], last_epoch=-1,
                                                     gamma=params['gamma'])
    summary(model, input_size=(params['input_size'],))
    val_metrics = _train_model(model, device, loss_fn, optimizer, lr_scheduler, epochs, train_loader, val_loader, True)
    return val_metrics
