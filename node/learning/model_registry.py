import torch.nn as nn
import torch.nn.functional as F
from torchvision import models


class LeNet5(nn.Module):
    def __init__(self, in_channels, num_classes):
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, 6, 5, padding=2)
        self.conv2 = nn.Conv2d(6, 16, 5)
        self.pool = nn.MaxPool2d(2)
        self.fc1 = nn.Linear(16 * 5 * 5, 120)
        self.fc2 = nn.Linear(120, 84)
        self.fc3 = nn.Linear(84, num_classes)

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = x.view(x.size(0), -1)
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        return self.fc3(x)


def _create_squeezenet(in_channels, num_classes):
    net = models.squeezenet1_1(weights=None)
    net.features[0] = nn.Conv2d(in_channels, 64, kernel_size=3, stride=1, padding=1)
    net.classifier[1] = nn.Conv2d(512, num_classes, kernel_size=1)
    net.num_classes = num_classes
    return net


def _create_mobilenetv2(in_channels, num_classes):
    net = models.mobilenet_v2(weights=None)
    net.features[0][0] = nn.Conv2d(in_channels, 32, kernel_size=3, stride=1, padding=1, bias=False)
    net.classifier[1] = nn.Linear(net.last_channel, num_classes)
    return net


def _create_resnet18(in_channels, num_classes):
    net = models.resnet18(weights=None)
    net.conv1 = nn.Conv2d(in_channels, 64, kernel_size=3, stride=1, padding=1, bias=False)
    net.maxpool = nn.Identity()
    net.fc = nn.Linear(512, num_classes)
    return net


MODEL_REGISTRY = {
    "lenet5": LeNet5,
    "squeezenet": _create_squeezenet,
    "mobilenetv2": _create_mobilenetv2,
    "resnet18": _create_resnet18,
}


def create_model(name, in_channels, num_classes):
    if name not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model '{name}'. Available: {list(MODEL_REGISTRY.keys())}")
    return MODEL_REGISTRY[name](in_channels, num_classes)
