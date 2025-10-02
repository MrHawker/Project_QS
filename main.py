from qiskit import QuantumCircuit, transpile, ClassicalRegister
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel,  ReadoutError, depolarizing_error
from qiskit_ibm_runtime import QiskitRuntimeService
from dotenv import load_dotenv
import os
import random

load_dotenv()

# Turn qubit q into a decoy which is one of |+>, |->, |y+> or |y->
def make_decoy(qc: QuantumCircuit, q:int, basis: str, sign: str):
    qc.reset(q)
    if basis == 'X':
        qc.h(q)
        if sign == '-':
            qc.z(q)
    elif basis == 'Y':
        qc.h(q)
        qc.s(q)
        if sign == '-':
            qc.z(q)
def projective_measurement_in_basis(qc: QuantumCircuit, q:int, c:int, basis:str):
    if basis == 'X':
        qc.h(q)
    elif basis == 'Y':
        qc.sdg(q)
        qc.h(q)
    else:
        raise ValueError("Basis must be either X or Y")
    qc.measure(q,c)


def eve_does_random_unitary_op(qc: QuantumCircuit, target_qubits: list[int], probability: float, random_generator: random.Random):
    for qubit in target_qubits:
        if random_generator.random() <= probability:
            gate = random_generator.choice(["X","Y","Z"])
            if gate == 'X':
                qc.x(qubit)
            elif gate == 'Y':
                qc.y(qubit)
            else:
                qc.z(qubit)

def eve_intercept_resend(qc: QuantumCircuit, probability: float, random_generator: random.Random):
    eve_classical_register = ClassicalRegister(qc.num_qubits)
    qc.add_register(eve_classical_register)
    for qubit in range(qc.num_qubits):
        if random_generator.random() <= probability:
            gate = random_generator.choice(["X","Y","Z"])
            if gate == 'X':
                qc.h(qubit)
            elif gate == 'Y':
                qc.sdg(qubit)
                qc.h(qubit)
            qc.measure(qubit, eve_classical_register[qubit])
            qc.reset(qubit)
            if gate == 'X':
                qc.h(qubit)
                if eve_classical_register[qubit] == 1:
                    qc.z(qubit)
            elif gate == 'Y':
                qc.h(qubit)
                qc.s(qubit)
                if eve_classical_register[qubit] == 1:
                    qc.z(qubit)


def create_noise_model():
    QiskitRuntimeService.save_account(token=os.getenv("IBM_API_KEY"), instance=os.getenv("INSTANCE_CRN"),overwrite=True)
    service = QiskitRuntimeService()
    least_busy_back_end = service.least_busy()
    noise_model = NoiseModel.from_backend(least_busy_back_end)
    return noise_model

def decoys_data_positions(random_generator:random.Random, number_of_qubits:int, number_of_decoys:int)-> tuple[list[int],list[int]]:
    decoys_positions = random_generator.sample(range(number_of_qubits),k=number_of_decoys)
    data_positions = []
    for i in range(number_of_qubits):
        if i not in decoys_positions:
            data_positions.append(i)
    return decoys_positions,data_positions
#Uses swap gate to move data qubits around while maintaining their relative positions with one another
def rearrange_data_qubits_in_circuits(qc:QuantumCircuit, current_data_positions:list[int], target_data_positions:list[int]):
    if len(current_data_positions) != len(target_data_positions):
        raise ValueError("Unequal length")
    n = len(current_data_positions)
    position_to_index = {}
    for i in range(n):
        position_to_index[current_data_positions[i]] = i
    for i in range(n):
        source = current_data_positions[i]
        destination = target_data_positions[i]
        if source == destination:
            continue
        try:
            k = position_to_index[destination]
        except:
            k = None
        qc.swap(source,destination)
        current_data_positions[i] = destination
        position_to_index[destination] = i
        if k is None:
            position_to_index.pop(source,None)
        else:
            current_data_positions[k] = source
            position_to_index[source] = k
            
def ring_quantum_circuit(number_of_qubits: int, decoy_rate:float, links: list[str], eve_attack_times: list[int],
                          random_generator: random.Random, eve: str = "off", eve_attack_probability :float = 3):
    
    qc = QuantumCircuit(number_of_qubits)
    number_of_decoys = int(number_of_qubits*decoy_rate)
    #Each iteration represent a send and receive step between Pi and Pi+1
    for i in range(len(links)):
        sender = links[i]
        reciever = links[(i+1) % len(links)]
        qc.barrier(label=f"{sender} make decoys")
        decoys_positions,data_positions = decoys_data_positions(random_generator,number_of_qubits,number_of_decoys)

