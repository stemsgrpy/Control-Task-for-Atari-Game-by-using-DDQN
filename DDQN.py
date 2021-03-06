import argparse
import os
import random
import torch
from torch.optim import Adam
from core.util import get_class_attr_val
from common.wrappers import make_atari, wrap_deepmind, wrap_pytorch
from config import Config
from buffer import ReplayBuffer
from model import CNNDQN
from trainer import Trainer
from tester import Tester

class CNNDDQNAgent:
    def __init__(self, config: Config):
        self.config = config
        self.is_training = True
        # self.buffer = deque(maxlen=self.config.max_buff)
        self.buffer = ReplayBuffer(self.config.max_buff)

        self.model = CNNDQN(self.config.state_shape, self.config.action_dim)
        self.target_model = CNNDQN(self.config.state_shape, self.config.action_dim)
        self.target_model.load_state_dict(self.model.state_dict())
        self.model_optim = Adam(self.model.parameters(), lr=self.config.learning_rate)

        if self.config.use_cuda:
            self.cuda()
    
    '''
    def pre_processing(observe):

        processed_observe = np.uint8(
            resize(rgb2gray(observe), (84, 84), mode='constant') * 255)

        return processed_observe
    '''
    
    '''
    def pre_process(observation):
        """Process (210, 160, 3) picture into (1, 84, 84)"""
        x_t = cv2.cvtColor(cv2.resize(observation, (84, 84)), cv2.COLOR_BGR2GRAY)
        ret, x_t = cv2.threshold(x_t, 1, 255, cv2.THRESH_BINARY)
        return np.reshape(x_t, (1, 84, 84)), x_t
    '''

    def act(self, state, epsilon=None):
        if epsilon is None: epsilon = self.config.epsilon_min
        if random.random() > epsilon or not self.is_training:
            # state = torch.tensor(state, dtype=torch.float).unsqueeze(0)
            state = torch.tensor(state, dtype=torch.float) # (1, 4, 84, 84)
            if self.config.use_cuda:
                state = state.cuda()
            q_value = self.model(state)
            action = q_value.max(1)[1].item()
        else:
            action = random.randrange(self.config.action_dim)
        return action

    def learning(self, fr):
        s0, a, r, s1, done = self.buffer.sample(self.config.batch_size)

        s0 = torch.tensor(s0, dtype=torch.float)
        s1 = torch.tensor(s1, dtype=torch.float)
        a = torch.tensor(a, dtype=torch.long)
        r = torch.tensor(r, dtype=torch.float)
        done = torch.tensor(done, dtype=torch.float)

        if self.config.use_cuda:
            s0 = s0.cuda()
            s1 = s1.cuda()
            a = a.cuda()
            r = r.cuda()
            done = done.cuda()

        q_values = self.model(s0).cuda()
        next_q_values = self.model(s1).cuda()
        next_q_state_values = self.target_model(s1).cuda()

        q_value = q_values.gather(1, a.unsqueeze(1)).squeeze(1)
        next_q_value = next_q_state_values.gather(1, next_q_values.max(1)[1].unsqueeze(1)).squeeze(1)
        expected_q_value = r + self.config.gamma * next_q_value * (1 - done)
        # Notice that detach the expected_q_value
        loss = (q_value - expected_q_value.detach()).pow(2).mean()

        self.model_optim.zero_grad()
        loss.backward()
        self.model_optim.step()

        if fr % self.config.update_tar_interval == 0:
            self.target_model.load_state_dict(self.model.state_dict())

        return loss.item()

    def cuda(self):
        self.model.cuda()
        self.target_model.cuda()

    def load_weights(self, model_path):
        model = torch.load(model_path)
        if 'model' in model:
            self.model.load_state_dict(model['model'])
        else:
            self.model.load_state_dict(model)

    def save_model(self, output, name=''):
        torch.save(self.model.state_dict(), '%s/model_%s.pkl' % (output, name))

    def save_config(self, output):
        with open(output + '/config.txt', 'w') as f:
            attr_val = get_class_attr_val(self.config)
            for k, v in attr_val.items():
                f.write(str(k) + " = " + str(v) + "\n")

    def save_checkpoint(self, fr, output):
        checkpath = output + '/checkpoint_model'
        os.makedirs(checkpath, exist_ok=True)
        torch.save({
            'frames': fr,
            'model': self.model.state_dict()
        }, '%s/checkpoint_fr_%d.tar'% (checkpath, fr))

    def load_checkpoint(self, model_path):
        checkpoint = torch.load(model_path)
        fr = checkpoint['frames']
        self.model.load_state_dict(checkpoint['model'])
        self.target_model.load_state_dict(checkpoint['model'])
        return fr

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--train', dest='train', action='store_true', help='train model')
    parser.add_argument('--test', dest='test', action='store_true', help='test model')
    parser.add_argument('--retrain', dest='retrain', action='store_true', help='retrain model')
    parser.add_argument('--env', default='PongNoFrameskip-v4', type=str, help='gym environment')
    parser.add_argument('--model_path', type=str, help='if test or retrain, import the model')
    args = parser.parse_args()

    config = Config()
    config.env = args.env
    config.gamma = 0.99         # discount_factor
    config.epsilon = 1          # epsilon start
    config.epsilon_min = 0.01   # epsilon final
    config.eps_decay = 120000    # 30000 BreakoutNoFrameskip-v4 -> 120000
    config.frames = 4000000
    config.use_cuda = True
    config.learning_rate = 1e-4
    config.max_buff = 400000 # 100000 # BreakoutNoFrameskip-v4 -> 400000
    config.update_tar_interval = 10000 # 1000 # BreakoutNoFrameskip-v4 -> 10000
    config.batch_size = 32
    config.print_interval = 5000
    config.log_interval = 5000
    config.checkpoint = True
    config.checkpoint_interval = 500000
    config.win_reward = 18      # PongNoFrameskip-v4
    config.win_break = True

    # handle the atari env
    env = make_atari(config.env)
    env = wrap_deepmind(env)
    env = wrap_pytorch(env)

    config.state_shape = env.observation_space.shape
    config.action_dim = env.action_space.n
    agent = CNNDDQNAgent(config)

    if args.train:
        trainer = Trainer(agent, env, config)
        trainer.train()

    elif args.test:
        if args.model_path is None:
            print('please add the model path:', '--model_path xxxx')
            exit(0)
        tester = Tester(agent, env, args.model_path)
        tester.test()

    elif args.retrain:
        if args.model_path is None:
            print('please add the model path:', '--model_path xxxx')
            exit(0)

        fr = agent.load_checkpoint(args.model_path)
        trainer = Trainer(agent, env, config)
        trainer.train(fr)
