/// L2 half of the delegation hierarchy. Contains no direct entrypoint for
/// authorisation -- the only way an authorisation is written is a message
/// arriving from the paired L1 WarfareAuthority contract, via Starknet's
/// native L1->L2 messaging. Command appointment never crosses the bridge
/// and has no representation here.

#[starknet::interface]
pub trait IL2AuthorisationRegistry<TContractState> {
    fn is_authorised(self: @TContractState, uxv: starknet::ContractAddress) -> bool;
    fn authorisation_of(self: @TContractState, uxv: starknet::ContractAddress) -> Authorisation;
    fn l1_authority(self: @TContractState) -> felt252;
}

#[derive(Drop, Copy, Serde, starknet::Store)]
pub struct Authorisation {
    pub domain: felt252,
    pub role: felt252,
    pub commander: felt252, // L1 address of the issuing commander, kept for audit
    pub granted_at: u64,
    pub active: bool,
}

#[starknet::contract]
pub mod L2AuthorisationRegistry {
    use starknet::ContractAddress;
    use starknet::get_block_timestamp;
    use starknet::storage::{
        Map, StoragePointerReadAccess, StoragePointerWriteAccess, StoragePathEntry,
    };
    use super::Authorisation;

    #[storage]
    struct Storage {
        l1_authority: felt252, // WarfareAuthority's L1 address; the only trusted sender
        authorisations: Map<ContractAddress, Authorisation>,
    }

    #[event]
    #[derive(Drop, starknet::Event)]
    pub enum Event {
        UxvAuthorised: UxvAuthorised,
    }

    #[derive(Drop, starknet::Event)]
    pub struct UxvAuthorised {
        #[key]
        pub uxv: ContractAddress,
        #[key]
        pub domain: felt252,
        pub role: felt252,
        pub commander: felt252,
        pub at: u64,
    }

    pub mod Errors {
        pub const UNTRUSTED_SENDER: felt252 = 'message not from L1 authority';
    }

    #[constructor]
    fn constructor(ref self: ContractState, l1_authority: felt252) {
        self.l1_authority.write(l1_authority);
    }

    /// Triggered by WarfareAuthority.authorise() on L1. `from_address` is
    /// populated by the sequencer from the L1 message itself -- it cannot be
    /// spoofed by an L2 caller, which is what makes the assert meaningful.
    #[l1_handler]
    fn authorise(
        ref self: ContractState,
        from_address: felt252,
        uxv: ContractAddress,
        domain: felt252,
        role: felt252,
        commander: felt252,
    ) {
        assert(from_address == self.l1_authority.read(), Errors::UNTRUSTED_SENDER);

        let at = get_block_timestamp();
        self
            .authorisations
            .entry(uxv)
            .write(Authorisation { domain, role, commander, granted_at: at, active: true });

        self.emit(UxvAuthorised { uxv, domain, role, commander, at });
    }

    #[abi(embed_v0)]
    impl L2AuthorisationRegistryImpl of super::IL2AuthorisationRegistry<ContractState> {
        fn is_authorised(self: @ContractState, uxv: ContractAddress) -> bool {
            self.authorisations.entry(uxv).read().active
        }

        fn authorisation_of(self: @ContractState, uxv: ContractAddress) -> Authorisation {
            self.authorisations.entry(uxv).read()
        }

        fn l1_authority(self: @ContractState) -> felt252 {
            self.l1_authority.read()
        }
    }
}
