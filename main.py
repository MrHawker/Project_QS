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
def ring_quantum_circuit(number_of_qubits: int, decoy_pos: list[int], links: list[str], eve_attack_times: list[int],
                          random_generator: random.Random, eve: str = "off", eve_attack_probability :float = 3):
    
    qc = QuantumCircuit(number_of_qubits)
