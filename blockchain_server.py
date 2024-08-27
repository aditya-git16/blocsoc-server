import random
import time
import hashlib
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

TOTAL_NODES = 300
TRANSACTIONS_PER_BLOCK = 5
ROUND_DURATION = 30  # seconds
INITIAL_REPUTATION = 100
MAX_REPUTATION = 1000
REPUTATION_DECAY = 0.99  # 1% decay per round
ONLINE_PROBABILITY = 0.95  # 95% chance a node is online each round

nodes = {}
transaction_pool = [
    "Alice sends 5 coins to Bob",
    "Charlie sends 3 coins to David",
    # ... (other transactions)
]

class Block:
    def __init__(self, transactions, previous_hash, proposer):
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.proposer = proposer
        self.timestamp = time.time()
        self.nonce = random.randint(1, 100000)
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        block_content = f"{self.transactions}{self.previous_hash}{self.proposer}{self.timestamp}{self.nonce}"
        return hashlib.sha256(block_content.encode()).hexdigest()

class Blockchain:
    def __init__(self):
        self.chain = [self.create_genesis_block()]

    def create_genesis_block(self):
        return Block(["Genesis Block"], "0", "System")

    def add_block(self, block):
        self.chain.append(block)

    def is_valid_block(self, block):
        return len(block.transactions) == TRANSACTIONS_PER_BLOCK and block.previous_hash == self.chain[-1].hash

blockchain = Blockchain()
proposed_block = None
votes = {}

@app.route('/ping', methods=['GET'])
def http_ping():
    current_time = time.time()
    total_nodes = len(nodes)
    online_nodes = sum(1 for node in nodes.values() if node['online'])
    total_reputation = sum(node['reputation'] for node in nodes.values())
    
    return jsonify({
        'timestamp': current_time,
        'total_nodes': total_nodes,
        'online_nodes': online_nodes,
        'average_reputation': total_reputation / total_nodes if total_nodes > 0 else 0,
        'chain_length': len(blockchain.chain)
    })

@app.route('/join', methods=['POST'])
def join():
    node_id = request.json['node_id']
    nodes[node_id] = {
        "blockchain": blockchain,
        "reputation": INITIAL_REPUTATION,
        "online": True
    }
    return jsonify({"status": "joined", "current_chain_length": len(blockchain.chain), "reputation": INITIAL_REPUTATION})

@socketio.on('propose_block')
def handle_block_proposal(data):
    global proposed_block
    node_id = data['node_id']
    if nodes[node_id]['online']:
        new_block = Block(data['transactions'], data['previous_hash'], node_id)
        proposed_block = new_block
        socketio.emit('new_block_proposal', {
            'proposer': node_id,
            'block_hash': new_block.hash,
            'transactions': new_block.transactions
        }, broadcast=True)

@socketio.on('vote_on_block')
def handle_vote(data):
    node_id = data['node_id']
    if nodes[node_id]['online'] and proposed_block and data['block_hash'] == proposed_block.hash:
        votes[node_id] = nodes[node_id]['reputation']

def select_proposer():
    online_nodes = [node_id for node_id, node_data in nodes.items() if node_data['online']]
    if not online_nodes:
        return None
    total_reputation = sum(nodes[node_id]['reputation'] for node_id in online_nodes)
    selection_point = random.uniform(0, total_reputation)
    current_point = 0
    for node_id in online_nodes:
        current_point += nodes[node_id]['reputation']
        if current_point >= selection_point:
            return node_id

def calculate_consensus():
    total_votes = sum(votes.values())
    total_reputation = sum(node['reputation'] for node in nodes.values() if node['online'])
    return total_votes > total_reputation / 2

def update_reputations(is_consensus_reached, is_valid_block):
    reputation_change = INITIAL_REPUTATION * 0.1  # 10% of initial reputation
    if is_consensus_reached and is_valid_block:
        nodes[proposed_block.proposer]['reputation'] += reputation_change
        for voter in votes.keys():
            nodes[voter]['reputation'] += reputation_change * 0.5
    elif not is_valid_block:
        nodes[proposed_block.proposer]['reputation'] -= reputation_change
        for voter in votes.keys():
            nodes[voter]['reputation'] -= reputation_change * 0.5
    
    # Apply decay and ensure reputation stays within bounds
    for node in nodes.values():
        node['reputation'] *= REPUTATION_DECAY
        node['reputation'] = max(1, min(MAX_REPUTATION, node['reputation']))

def consensus_round():
    global proposed_block
    round_number = 0
    while True:
        round_number += 1
        proposed_block = None
        votes.clear()
        
        # Randomly set nodes online/offline
        for node in nodes.values():
            node['online'] = random.random() < ONLINE_PROBABILITY
        
        proposer = select_proposer()
        if proposer:
            available_transactions = random.sample(transaction_pool, TRANSACTIONS_PER_BLOCK * 2)
            
            socketio.emit('round_start', {
                'round': round_number,
                'proposer': proposer,
                'available_transactions': available_transactions,
                'current_chain_length': len(blockchain.chain)
            })
            
            time.sleep(ROUND_DURATION)
            
            is_consensus_reached = calculate_consensus()
            is_valid_block = proposed_block and blockchain.is_valid_block(proposed_block)
            
            if is_consensus_reached and is_valid_block:
                blockchain.add_block(proposed_block)
                update_reputations(True, True)
                socketio.emit('round_end', {
                    'round': round_number,
                    'winning_block': {
                        'hash': proposed_block.hash,
                        'proposer': proposed_block.proposer,
                        'transactions': proposed_block.transactions
                    },
                    'new_chain_length': len(blockchain.chain)
                })
            else:
                update_reputations(is_consensus_reached, is_valid_block)
                socketio.emit('round_end', {
                    'round': round_number,
                    'error': 'No consensus reached or invalid block proposed'
                })
        else:
            socketio.emit('round_end', {
                'round': round_number,
                'error': 'No online nodes available to propose a block'
            })
        
        # Broadcast updated reputations
        socketio.emit('reputation_update', {node_id: node['reputation'] for node_id, node in nodes.items()})

if __name__ == '__main__':
    socketio.start_background_task(consensus_round)
    socketio.run(app, host='0.0.0.0', port=5001)