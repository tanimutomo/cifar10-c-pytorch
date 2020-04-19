import argparse
import glob
import numpy as np
import os
import pprint
from skimage import draw
import torch
import torchvision
import tqdm

from glob import glob
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import transforms, datasets
from tqdm import tqdm

from utils import load_txt, accuracy, create_barplot, get_fname, AverageMeter
from models.resnet import ResNet56
from dataset import CIFAR10C

corruptions = load_txt('./src/corruptions.txt')
MEAN = [0.49139968, 0.48215841, 0.44653091]
STD = [0.24703223, 0.24348513, 0.26158784]

class Standadize(object):
    def __init__(self):
        pass
    
    def __call__(self, x :torch.FloatTensor) -> torch.FloatTensor:
        return (x - x.min()) / (x.max() - x.min())

def batch_standadize(x):
    mn, _ = x.view(x.shape[0], -1).min(dim=1)
    mx, _ = x.view(x.shape[0], -1).max(dim=1)
    return (x - mn[:, None, None, None]) / (mx - mn)[:, None, None, None]

def normalize(x):
    x -= torch.tensor(MEAN, device=x.device)[None, :, None, None]
    x /= torch.tensor(STD, device=x.device)[None, :, None, None]
    return x

def zshift(z :torch.FloatTensor) -> torch.FloatTensor:
    assert z.ndim == 5 and z.shape[-1] == 2 and z.shape[-2] == z.shape[-3]
    resol = z.shape[-2]
    return torch.cat([
        torch.cat([
            z[..., resol//2:, resol//2:, :], # bottom right
            z[..., resol//2:, :resol//2, :], # bottom left
        ], dim=-2),
        torch.cat([
            z[..., :resol//2, resol//2:, :], # top right
            z[..., :resol//2, :resol//2, :], # top left
        ], dim=-2),
    ], dim=-3)


def _get_circle_mask(shape, br, er):
    B, C, H, W, F = shape
    assert H == W
    c = H // 2
    lm = torch.zeros(shape)
    sm = torch.zeros(shape)
    if er > 0:
        rr, cc = draw.circle(c, c, er)
        lm[..., rr, cc, :] = 1
    else:
        lm = torch.ones(shape)
    if br > 0:
        rr, cc = draw.circle(c, c, br)
        sm[..., rr, cc, :] = 1
    return lm - sm


def main(opt, weight_path :str):

    device = torch.device(opt.gpu_id)

    # model
    if opt.arch == 'resnet56':
        model = ResNet56()
    else:
        raise ValueError()
    try:
        model.load_state_dict(torch.load(weight_path, map_location='cpu'))
    except:
        model.load_state_dict(torch.load(weight_path, map_location='cpu')['model'])
    model.to(device)
    model.eval()

    transform = transforms.Compose([
        transforms.ToTensor(),
        # Standadize(),
        transforms.Normalize(MEAN, STD)
    ])

    accs = dict()
    with tqdm(total=len(opt.corruptions), ncols=80) as pbar:
        for ci, cname in enumerate(opt.corruptions):
            # load dataset
            if cname == 'natural':
                dataset = datasets.CIFAR10(
                    os.path.join(opt.data_root, 'cifar10'),
                    train=False, transform=transform, download=True,
                )
            else:
                dataset = CIFAR10C(
                    os.path.join(opt.data_root, 'cifar10-c'),
                    cname, transform=transform
                )
            loader = DataLoader(dataset, batch_size=opt.batch_size,
                                shuffle=False, num_workers=4)
            
            acc_meter = AverageMeter()
            with torch.no_grad():
                for itr, (x, y) in enumerate(loader):
                    x = x.to(device, non_blocking=True)
                    y = y.to(device, dtype=torch.int64, non_blocking=True)

                    # z = torch.fft(torch.stack([x, x], dim=-1), 2)
                    # z_ = zshift(z)
                    # z_ = z_ * _get_circle_mask(z_.shape, 1, 10).to(device)
                    # z = zshift(z_)
                    # x = torch.ifft(z, 2)[..., 0]
                    # x = normalize(batch_standadize(x))

                    z = model(x)
                    loss = F.cross_entropy(z, y)
                    acc, _ = accuracy(z, y, topk=(1, 5))
                    acc_meter.update(acc.item())

            accs[f'{cname}'] = acc_meter.avg

            pbar.set_postfix_str(f'{cname}: {acc_meter.avg:.2f}')
            pbar.update()
    
    avg = np.mean(list(accs.values()))
    accs['avg'] = avg

    pprint.pprint(accs)
    save_name = get_fname(weight_path)
    create_barplot(
        accs, save_name + f' / avg={avg:.2f}',
        os.path.join(opt.fig_dir, save_name+'.png')
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        '--arch',
        type=str, default='resnet56',
        help='model name'
    )
    parser.add_argument(
        '--weight_dir',
        type=str,
        help='path to the dicrectory containing model weights',
    )
    parser.add_argument(
        '--weight_path',
        type=str,
        help='path to the dicrectory containing model weights',
    )
    parser.add_argument(
        '--fig_dir',
        type=str, default='figs',
        help='path to the dicrectory saving output figure',
    )
    parser.add_argument(
        '--data_root',
        type=str, default='/home/tanimu/data',
        help='root path to cifar10-c directory'
    )
    parser.add_argument(
        '--batch_size',
        type=int, default=1024,
        help='batch size',
    )
    parser.add_argument(
        '--corruptions',
        type=str, nargs='*',
        default=corruptions,
        help='testing corruption types',
    )
    parser.add_argument(
        '--gpu_id',
        type=str, default=0,
        help='gpu id to use'
    )

    opt = parser.parse_args()

    if opt.weight_path is not None:
        main(opt, opt.weight_path)
    elif opt.weight_dir is not None:
        for path in glob(f'./{opt.weight_dir}/*.pth'):
            print('\n', path)
            main(opt, path)
    else:
        raise ValueError()