import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import init
import random
import numpy as np

def get_onehot(idx, size):
    t = torch.zeros(size)
    t[idx] = 1.
    return t

def init_emb2pos(trainer, args):
    '''matrix version, unused
    Usage: 
        # emb_u.shape: [batch_size, walk_length, dim]
        batch_emb2posu = torch.stack([emb2posu] * batch_size, dim=0) # shape: [batch_size, num_pos, walk_length]
        emb_pos_u = torch.bmm(batch_emb2posu, emb_u) # shape: [batch_size, num_pos, dim]
    '''
    idx_list_u = []
    idx_list_v = []
    for i in range(args.walk_length):
        for j in range(i-args.window_size, i):
            if j >= 0:
                idx_list_u.append(j)
                idx_list_v.append(i)
        for j in range(i+1, i+1+args.window_size):
            if j < args.walk_length:
                idx_list_u.append(j)
                idx_list_v.append(i)

    # [num_pos, walk_length]
    emb2posu = torch.stack([get_onehot(idx, args.walk_length) for idx in idx_list_u]).to(trainer.device)#.to_sparse()
    emb2posv = torch.stack([get_onehot(idx, args.walk_length) for idx in idx_list_v]).to(trainer.device)#.to_sparse()
    return emb2posu, emb2posv

def init_emb2pos_index(trainer, args, batch_size):
    '''index version
    Usage:
        # emb_u.shape: [batch_size * walk_length, dim]
        batch_emb2posu = torch.index_select(emb_u, 0, pos_u_index)
    '''
    idx_list_u = []
    idx_list_v = []
    for b in range(batch_size):
        for i in range(args.walk_length):
            for j in range(i-args.window_size, i):
                if j >= 0:
                    idx_list_u.append(j + b * batch_size)
                    idx_list_v.append(i + b * batch_size)
            for j in range(i+1, i+1+args.window_size):
                if j < args.walk_length:
                    idx_list_u.append(j + b * batch_size)
                    idx_list_v.append(i + b * batch_size)

    # [num_pos * batch_size]
    index_emb_posu = torch.LongTensor(idx_list_u).to(trainer.device)
    index_emb_posv = torch.LongTensor(idx_list_v).to(trainer.device)

    return index_emb_posu, index_emb_posv

def init_emb2neg_index(trainer, args, batch_size):
    idx_list_u = []
    for i in range(batch_size):
        for j in range(args.negative):
            idx_in_batch_u = i * args.walk_length
            idx_list_u += list(range(idx_in_batch_u, idx_in_batch_u + args.walk_length))
    
    idx_list_v = list(range(batch_size * args.walk_length)) * args.negative
    random.shuffle(idx_list_v)

    # [bs * walk_length * negative]
    index_emb_negu = torch.LongTensor(idx_list_u).to(trainer.device)
    index_emb_negv = torch.LongTensor(idx_list_v).to(trainer.device)
    return index_emb_negu, index_emb_negv

def init_emb2neg(trainer, args, batch_size):
    idx_list_u = []
    idx_list_v = []
    for i in range(batch_size):
        for j in range(args.negative):
            idx_in_batch_u = i * args.walk_length
            idx_list_u += list(range(idx_in_batch_u, idx_in_batch_u + args.walk_length))
            idx_in_batch_v = (i + j + 1) % batch_size * args.walk_length
            idx_list_v += list(range(idx_in_batch_v, idx_in_batch_v + args.walk_length))

    # [bs * walk_length * negative, bs * walk_length]
    emb2negu = torch.stack([get_onehot(idx, args.walk_length * batch_size) for idx in idx_list_u]).to(trainer.device)#.to_sparse()
    emb2negv = torch.stack([get_onehot(idx, args.walk_length * batch_size) for idx in idx_list_v]).to(trainer.device)#.to_sparse()
    return emb2negu, emb2negv

def init_grad2pos(trainer, args, emb2posu, emb2posv):
    cnt = 0
    grad2posu = torch.clone(emb2posu)#.to_dense()
    grad2posv = torch.clone(emb2posv)#.to_dense()
    for i in range(args.walk_length):
        for j in range(i-args.window_size, i):
            if j >= 0:
                coeff = 1 - float(i - j - 1) / args.window_size
                grad2posu[cnt] *= coeff
                grad2posv[cnt] *= coeff
                cnt += 1
        for j in range(i+1, i+1+args.window_size):
            if j < args.walk_length:
                coeff = 1 - float(j - i - 1) / args.window_size
                grad2posu[cnt] *= coeff
                grad2posv[cnt] *= coeff
                cnt += 1

    # [walk_length, num_pos]
    return grad2posu.T, grad2posv.T#.to_sparse()

def init_empty_grad(trainer, args, batch_size):
    grad_u = torch.zeros((batch_size * args.walk_length, trainer.emb_dimension)).to(trainer.device)
    grad_v = torch.zeros((batch_size * args.walk_length, trainer.emb_dimension)).to(trainer.device)

    return grad_u, grad_v

class SkipGramModel(nn.Module):

    def __init__(self, emb_size, emb_dimension, device, args):
        super(SkipGramModel, self).__init__()
        self.emb_size = emb_size
        self.emb_dimension = emb_dimension
        self.device = device
        self.mixed_train = args.mix
        self.neg_weight = args.neg_weight
        self.negative = args.negative
        self.args = args
        # content embedding
        self.u_embeddings = nn.Embedding(emb_size, emb_dimension, sparse=True)
        # context embedding
        self.v_embeddings = nn.Embedding(emb_size, emb_dimension, sparse=True)

        self.lookup_table = torch.sigmoid(torch.arange(-6.01, 6.01, 0.01).to(device))
        self.lookup_table[0] = 0.
        self.lookup_table[-1] = 1.

        self.index_emb_posu, self.index_emb_posv = init_emb2pos_index(self, args, args.batch_size)
        self.index_emb_negu, self.index_emb_negv = init_emb2neg_index(self, args, args.batch_size)
        self.grad_u, self.grad_v = init_empty_grad(self, args, self.batch_size)

        initrange = 1.0 / self.emb_dimension
        init.uniform_(self.u_embeddings.weight.data, -initrange, initrange)
        init.constant_(self.v_embeddings.weight.data, 0)

    def share_memory(self):
        self.u_embeddings.weight.share_memory_()
        self.v_embeddings.weight.share_memory_()
        self.index_emb_posu.share_memory_()
        self.index_emb_posv.share_memory_()
        self.index_emb_negu.share_memory_()
        self.index_emb_negv.share_memory_()
        self.grad_u.share_memory_()
        self.grad_v.share_memory_()
        self.lookup_table.share_memory_()

    def fast_learn_super(self, batch_walks, lr, neg_v=None):
        # [batch_size, walk_length]
        nodes = torch.stack(batch_walks)
        if self.args.only_gpu:
            nodes = nodes.to(self.device)

        emb_u = self.u_embeddings.weight[nodes].view(-1, self.emb_dimension).to(self.device)
        emb_v = self.v_embeddings.weight[nodes].view(-1, self.emb_dimension).to(self.device)

        ## Postive
        bs = len(batch_walks)
        if bs < self.args.batch_size:
            index_emb_posu, index_emb_posv = init_emb2pos_index(self, self.args, bs)
        else:
            index_emb_posu = self.index_emb_posu
            index_emb_posv = self.index_emb_posv

        # num_pos: the number of positive node pairs generated by a single walk sequence
        # [batch_size * num_pos, dim]
        emb_pos_u = torch.index_select(emb_u, 0, index_emb_posu)
        emb_pos_v = torch.index_select(emb_v, 0, index_emb_posv)

        pos_score = torch.sum(torch.mul(emb_pos_u, emb_pos_v), dim=1)
        pos_score = torch.clamp(pos_score, max=6, min=-6)
        idx = torch.floor((pos_score + 6.01) / 0.01).long()
        # [batch_size * num_pos]
        sigmoid_score = self.lookup_table[idx]
        # [batch_size * num_pos, 1]
        sigmoid_score = (1 - sigmoid_score).unsqueeze(1)

        # [batch_size * num_pos, dim]
        grad_u_pos = sigmoid_score * emb_pos_v
        grad_v_pos = sigmoid_score * emb_pos_u
        # [batch_size * walk_length, dim]
        if bs < self.args.batch_size:
            grad_u, grad_v = init_empty_grad(self, args, bs)
        else:
            self.grad_u.zero_()
            self.grad_v.zero_()
            grad_u = self.grad_u
            grad_v = self.grad_v
        grad_u.index_add_(0, index_emb_posu, grad_u_pos)
        grad_v.index_add_(0, index_emb_posv, grad_v_pos)

        ## Negative
        if bs < self.args.batch_size:
            index_emb_negu, index_emb_negv = init_emb2neg_index(self, self.args, bs)
        else:
            index_emb_negu = self.index_emb_negu
            index_emb_negv = self.index_emb_negv

        emb_neg_u = torch.index_select(emb_u, 0, index_emb_negu)
        emb_neg_v = torch.index_select(emb_v, 0, index_emb_negv)

        # [batch_size * walk_length * negative, dim]
        neg_score = torch.sum(torch.mul(emb_neg_u, emb_neg_v), dim=1)
        neg_score = torch.clamp(neg_score, max=6, min=-6)
        idx = torch.floor((neg_score + 6.01) / 0.01).long()
        sigmoid_score = - self.lookup_table[idx]
        sigmoid_score = sigmoid_score.unsqueeze(1)

        grad_u_neg = self.args.neg_weight * sigmoid_score * emb_neg_v
        grad_v_neg = self.args.neg_weight * sigmoid_score * emb_neg_u

        grad_u.index_add_(0, index_emb_negu, grad_u_neg)
        grad_v.index_add_(0, index_emb_negv, grad_v_neg)

        grad_u *= lr
        grad_v *= lr

        if self.mixed_train:
            grad_u = grad_u.cpu()
            grad_v = grad_v.cpu()
            
        self.u_embeddings.weight.data.index_add_(0, nodes.view(-1), grad_u)
        self.v_embeddings.weight.data.index_add_(0, nodes.view(-1), grad_v)

        return

    def fast_learn_multi(self, pos_u, pos_v, neg_u, neg_v, lr):
        """ multi-sequence learning, unused """
        # pos_u [batch_size, num_pos]
        # pos_v [batch_size, num_pos]
        # neg_u [batch_size, walk_length]
        # neg_v [batch_size, negative]
        # [batch_size, num_pos, dim]
        emb_u = self.u_embeddings.weight[pos_u]
        # [batch_size, num_pos, dim]
        emb_v = self.v_embeddings.weight[pos_v]
        # [batch_size, walk_length, dim]
        emb_neg_u = self.u_embeddings.weight[neg_u]
        # [batch_size, negative, dim]
        emb_neg_v = self.v_embeddings.weight[neg_v]

        if self.mixed_train:
            emb_u = emb_u.to(self.device)
            emb_v = emb_v.to(self.device)
            emb_neg_u = emb_neg_u.to(self.device)
            emb_neg_v = emb_neg_v.to(self.device)

        pos_score = torch.sum(torch.mul(emb_u, emb_v), dim=2)
        pos_score = torch.clamp(pos_score, max=6, min=-6)
        idx = torch.floor((pos_score + 6.01) / 0.01)
        idx = idx.long()
        # [batch_size, num_pos]
        sigmoid_score = self.lookup_table[idx]
        # [batch_size, num_pos, 1]
        sigmoid_score = (1 - sigmoid_score).unsqueeze(2)

        grad_v = sigmoid_score * emb_u
        grad_v = grad_v.view(-1, self.emb_dimension)
        grad_u = sigmoid_score * emb_v
        grad_u = grad_u.view(-1, self.emb_dimension)

        # [batch_size, walk_length, negative]
        neg_score = emb_neg_u.bmm(emb_neg_v.transpose(1,2)) 
        neg_score = torch.clamp(neg_score, max=6, min=-6)
        idx = torch.floor((neg_score + 6.01) / 0.01)
        idx = idx.long()
        sigmoid_score = self.lookup_table[idx]
        sigmoid_score = - sigmoid_score

        # [batch_size, negative, dim]
        grad_neg_v = sigmoid_score.transpose(1,2).bmm(emb_neg_u)
        grad_neg_v = grad_neg_v.view(-1, self.emb_dimension)
        # [batch_size, walk_length, dim]
        grad_neg_u = sigmoid_score.bmm(emb_neg_v)
        grad_neg_u = grad_neg_u.view(-1, self.emb_dimension)

        grad_v *= lr
        grad_u *= lr
        grad_neg_v *= self.neg_weight * lr
        grad_neg_u *= self.neg_weight * lr 

        if self.mixed_train:
            grad_v = grad_v.cpu()
            grad_u = grad_u.cpu()
            grad_neg_v = grad_neg_v.cpu()
            grad_neg_u = grad_neg_u.cpu()
            pos_v = pos_v.cpu()
            pos_u = pos_u.cpu()
            neg_v = neg_v.cpu()
            neg_u = neg_u.cpu()

        self.v_embeddings.weight.index_add_(0, pos_v.view(-1), grad_v)
        self.v_embeddings.weight.index_add_(0, neg_v.view(-1), grad_neg_v)
        self.u_embeddings.weight.index_add_(0, pos_u.view(-1), grad_u)
        self.u_embeddings.weight.index_add_(0, neg_u.view(-1), grad_neg_u)

        return

    def fast_learn_single(self, pos_u, pos_v, neg_u, neg_v, lr):
        """ single-sequence learning, unused """
        # pos_u [num_pos]
        # pos_v [num_pos]
        # neg_u [walk_length]
        # neg_v [negative]
        emb_u = self.u_embeddings(pos_u)
        emb_v = self.v_embeddings(pos_v)
        emb_neg_u = self.u_embeddings(neg_u)
        emb_neg_v = self.v_embeddings(neg_v)

        pos_score = torch.sum(torch.mul(emb_u, emb_v), dim=1)
        pos_score = torch.clamp(pos_score, max=6, min=-6)
        idx = torch.floor((pos_score + 6.01) / 0.01)
        idx = idx.long()
        sigmoid_score = self.lookup_table[idx]
        sigmoid_score = (1 - sigmoid_score).unsqueeze(1)

        grad_v = torch.clone(sigmoid_score * self.u_embeddings.weight[pos_u])
        grad_u = torch.clone(sigmoid_score * self.v_embeddings.weight[pos_v])

        neg_score = emb_neg_u.mm(emb_neg_v.T) # [batch_size, negative_size]
        neg_score = torch.clamp(neg_score, max=6, min=-6)
        idx = torch.floor((neg_score + 6.01) / 0.01)
        idx = idx.long()
        sigmoid_score = self.lookup_table[idx]
        sigmoid_score = - sigmoid_score

        #neg_size = neg_score.shape[1]
        grad_neg_v = torch.clone(sigmoid_score.T.mm(emb_neg_u))
        grad_neg_u = torch.clone(sigmoid_score.mm(emb_neg_v)) 


        self.v_embeddings.weight.index_add_(0, pos_v, lr * grad_v)
        self.v_embeddings.weight.index_add_(0, neg_v, lr * grad_neg_v)
        self.u_embeddings.weight.index_add_(0, pos_u, lr * grad_u)
        self.u_embeddings.weight.index_add_(0, neg_u, lr * grad_neg_u)

        return

    def forward(self, pos_u, pos_v, neg_v):
        ''' unused '''
        emb_u = self.u_embeddings(pos_u)
        emb_v = self.v_embeddings(pos_v)
        emb_neg_v = self.v_embeddings(neg_v)

        score = torch.sum(torch.mul(emb_u, emb_v), dim=1)
        score = torch.clamp(score, max=6, min=-6)
        score = -F.logsigmoid(score)

        neg_score = torch.bmm(emb_neg_v, emb_u.unsqueeze(2)).squeeze()
        neg_score = torch.clamp(neg_score, max=6, min=-6)
        neg_score = -torch.sum(F.logsigmoid(-neg_score), dim=1)

        #return torch.mean(score + neg_score)
        return torch.sum(score), torch.sum(neg_score)

    def save_embedding(self, dataset, file_name):
        embedding = self.u_embeddings.weight.cpu().data.numpy()
        with open(file_name, 'w') as f:
            f.write('%d %d\n' % (self.emb_size, self.emb_dimension))
            for wid in range(self.emb_size):
                e = ' '.join(map(lambda x: str(x), embedding[wid]))
                f.write('%s %s\n' % (str(dataset.id2node[wid]), e))
