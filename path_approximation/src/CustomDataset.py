from typing import Union

import numpy as np
import torch
from torch.utils.data import Dataset

from utils import is_numpy_array


class CustomDataset(Dataset):

    def __init__(self, x: Union[np.array, torch.Tensor], y: Union[np.array, torch.Tensor], transform=None):
        if is_numpy_array(x):
            x = torch.from_numpy(x.astype(np.float32))
        if is_numpy_array(y):
            y = torch.from_numpy(y.astype(np.float32))
        self.x = x
        self.y = y.unsqueeze(1)
        self.transform = transform

    def __getitem__(self, index):
        x, y = self.x[index], self.y[index]
        if self.transform:
            x = self.transform(x)
        return x, y

    def __len__(self):
        return len(self.x)