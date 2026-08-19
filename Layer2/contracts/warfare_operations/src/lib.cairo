/// Three simulated warfare-domain operations (AAW, ASuW, ASW). Each is gated
/// by the authority already bridged from L1 via the AuthorisationRegistry:
/// execution succeeds only for a caller whose authorisation is active AND in
/// this contract's specific domain. Wrong domain and no authorisation both
/// fail the same assertion -- this is the point where "authorised" starts to
/// mean something operationally, rather than just being recorded state.

pub mod common {
    use starknet::ContractAddress;

    /// Must match the field order of the deployed L2AuthorisationRegistry's
    /// Authorisation struct exactly -- Serde decodes positionally, not by
    /// struct name, so this only needs to be layout-compatible.
    #[derive(Drop, Copy, Serde)]
    pub struct Authorisation {
        pub domain: felt252,
        pub role: felt252,
        pub commander: felt252,
        pub granted_at: u64,
        pub active: bool,
    }

    #[starknet::interface]
    pub trait IL2AuthorisationRegistry<TContractState> {
        fn authorisation_of(self: @TContractState, uxv: ContractAddress) -> Authorisation;
    }

    #[starknet::interface]
    pub trait IWarfareOperation<TContractState> {
        fn execute(ref self: TContractState, contact_ref: felt252);
        fn total_executions(self: @TContractState) -> u64;
        fn registry(self: @TContractState) -> ContractAddress;
    }
}

#[starknet::contract]
pub mod AAWOperation {
    use starknet::{ContractAddress, get_caller_address, get_block_timestamp};
    use starknet::storage::{StoragePointerReadAccess, StoragePointerWriteAccess};
    use super::common::{IL2AuthorisationRegistryDispatcher, IL2AuthorisationRegistryDispatcherTrait};

    const REQUIRED_DOMAIN: felt252 = 1; // Air -- Anti-Air Warfare

    #[storage]
    struct Storage {
        registry: ContractAddress,
        total_executions: u64,
    }

    #[event]
    #[derive(Drop, starknet::Event)]
    pub enum Event {
        OperationExecuted: OperationExecuted,
    }

    #[derive(Drop, starknet::Event)]
    pub struct OperationExecuted {
        #[key]
        pub uxv: ContractAddress,
        pub contact_ref: felt252,
        pub at: u64,
    }

    pub mod Errors {
        pub const NOT_AUTHORISED: felt252 = 'uxv not authorised for domain';
    }

    #[constructor]
    fn constructor(ref self: ContractState, registry: ContractAddress) {
        self.registry.write(registry);
    }

    #[abi(embed_v0)]
    impl AAWOperationImpl of super::common::IWarfareOperation<ContractState> {
        fn execute(ref self: ContractState, contact_ref: felt252) {
            let caller = get_caller_address();
            let auth = IL2AuthorisationRegistryDispatcher { contract_address: self.registry.read() }
                .authorisation_of(caller);
            assert(auth.active, Errors::NOT_AUTHORISED);
            assert(auth.domain == REQUIRED_DOMAIN, Errors::NOT_AUTHORISED);

            self.total_executions.write(self.total_executions.read() + 1);
            self.emit(OperationExecuted { uxv: caller, contact_ref, at: get_block_timestamp() });
        }

        fn total_executions(self: @ContractState) -> u64 {
            self.total_executions.read()
        }

        fn registry(self: @ContractState) -> ContractAddress {
            self.registry.read()
        }
    }
}

#[starknet::contract]
pub mod ASuWOperation {
    use starknet::{ContractAddress, get_caller_address, get_block_timestamp};
    use starknet::storage::{StoragePointerReadAccess, StoragePointerWriteAccess};
    use super::common::{IL2AuthorisationRegistryDispatcher, IL2AuthorisationRegistryDispatcherTrait};

    const REQUIRED_DOMAIN: felt252 = 3; // Surface -- Anti-Surface Warfare

    #[storage]
    struct Storage {
        registry: ContractAddress,
        total_executions: u64,
    }

    #[event]
    #[derive(Drop, starknet::Event)]
    pub enum Event {
        OperationExecuted: OperationExecuted,
    }

    #[derive(Drop, starknet::Event)]
    pub struct OperationExecuted {
        #[key]
        pub uxv: ContractAddress,
        pub contact_ref: felt252,
        pub at: u64,
    }

    pub mod Errors {
        pub const NOT_AUTHORISED: felt252 = 'uxv not authorised for domain';
    }

    #[constructor]
    fn constructor(ref self: ContractState, registry: ContractAddress) {
        self.registry.write(registry);
    }

    #[abi(embed_v0)]
    impl ASuWOperationImpl of super::common::IWarfareOperation<ContractState> {
        fn execute(ref self: ContractState, contact_ref: felt252) {
            let caller = get_caller_address();
            let auth = IL2AuthorisationRegistryDispatcher { contract_address: self.registry.read() }
                .authorisation_of(caller);
            assert(auth.active, Errors::NOT_AUTHORISED);
            assert(auth.domain == REQUIRED_DOMAIN, Errors::NOT_AUTHORISED);

            self.total_executions.write(self.total_executions.read() + 1);
            self.emit(OperationExecuted { uxv: caller, contact_ref, at: get_block_timestamp() });
        }

        fn total_executions(self: @ContractState) -> u64 {
            self.total_executions.read()
        }

        fn registry(self: @ContractState) -> ContractAddress {
            self.registry.read()
        }
    }
}

#[starknet::contract]
pub mod ASWOperation {
    use starknet::{ContractAddress, get_caller_address, get_block_timestamp};
    use starknet::storage::{StoragePointerReadAccess, StoragePointerWriteAccess};
    use super::common::{IL2AuthorisationRegistryDispatcher, IL2AuthorisationRegistryDispatcherTrait};

    const REQUIRED_DOMAIN: felt252 = 2; // Subsurface -- Anti-Submarine Warfare

    #[storage]
    struct Storage {
        registry: ContractAddress,
        total_executions: u64,
    }

    #[event]
    #[derive(Drop, starknet::Event)]
    pub enum Event {
        OperationExecuted: OperationExecuted,
    }

    #[derive(Drop, starknet::Event)]
    pub struct OperationExecuted {
        #[key]
        pub uxv: ContractAddress,
        pub contact_ref: felt252,
        pub at: u64,
    }

    pub mod Errors {
        pub const NOT_AUTHORISED: felt252 = 'uxv not authorised for domain';
    }

    #[constructor]
    fn constructor(ref self: ContractState, registry: ContractAddress) {
        self.registry.write(registry);
    }

    #[abi(embed_v0)]
    impl ASWOperationImpl of super::common::IWarfareOperation<ContractState> {
        fn execute(ref self: ContractState, contact_ref: felt252) {
            let caller = get_caller_address();
            let auth = IL2AuthorisationRegistryDispatcher { contract_address: self.registry.read() }
                .authorisation_of(caller);
            assert(auth.active, Errors::NOT_AUTHORISED);
            assert(auth.domain == REQUIRED_DOMAIN, Errors::NOT_AUTHORISED);

            self.total_executions.write(self.total_executions.read() + 1);
            self.emit(OperationExecuted { uxv: caller, contact_ref, at: get_block_timestamp() });
        }

        fn total_executions(self: @ContractState) -> u64 {
            self.total_executions.read()
        }

        fn registry(self: @ContractState) -> ContractAddress {
            self.registry.read()
        }
    }
}
