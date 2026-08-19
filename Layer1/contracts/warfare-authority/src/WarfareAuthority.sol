// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IStarknetCore {
    function sendMessageToL2(
        uint256 toAddress,
        uint256 selector,
        uint256[] calldata payload
    ) external payable returns (bytes32);
}

/// @title WarfareAuthority
/// @notice L1 half of the delegation hierarchy. Command (COMSNMG1) appoints
/// warfare commanders among the coalition ships; an appointed commander
/// authorises a UxV for its domain by sending a message to the L2
/// AuthorisationRegistry via Starknet's native L1->L2 messaging. Command
/// appointment never crosses the bridge -- only authorisation does.
contract WarfareAuthority {
    // Domain codes. Kept as small integers, not ASCII strings: Solidity's
    // bytes32("AIR") and Cairo's 'AIR' short-string literal do not encode to
    // the same numeric value, so a shared symbolic string would silently
    // desynchronise the two sides. Both contracts share this table only by
    // convention.
    //   1 = Air          2 = Subsurface          3 = Surface
    uint256 public constant DOMAIN_AIR = 1;
    uint256 public constant DOMAIN_SUBSURFACE = 2;
    uint256 public constant DOMAIN_SURFACE = 3;

    address public immutable command;
    IStarknetCore public immutable starknetCore;
    uint256 public immutable l2Registry;

    // Starknet selector for the L2 #[l1_handler] entrypoint named `authorise`.
    // Compute with (starknet.js is already a dependency in the driver):
    //   node -e "console.log(require('starknet').hash.getSelectorFromName('authorise'))"
    // MUST be replaced before deployment -- this placeholder is intentionally wrong.
    uint256 public constant AUTHORISE_SELECTOR = 0x2cc3f86925ebe7f31ea32a193535d5c06237c6c41ed679451e720036b2de3b8; // TODO: fill in before deploy

    mapping(address => uint256) public commanderDomain; // 0 = not appointed

    event CommanderAppointed(address indexed commander, uint256 indexed domain);
    event CommanderRemoved(address indexed commander);
    event UxvAuthorised(uint256 indexed uxvL2Address, uint256 indexed domain, address indexed commander, uint256 role);

    error NotCommand();
    error NotCommander();
    error ZeroDomain();
    error AlreadyAppointed();
    error NotAppointed();

    modifier onlyCommand() {
        if (msg.sender != command) revert NotCommand();
        _;
    }

    constructor(address _command, address _starknetCore, uint256 _l2Registry) {
        command = _command;
        starknetCore = IStarknetCore(_starknetCore);
        l2Registry = _l2Registry;
    }

    function appointCommander(address commander, uint256 domain) external onlyCommand {
        if (domain == 0) revert ZeroDomain();
        if (commanderDomain[commander] != 0) revert AlreadyAppointed();
        commanderDomain[commander] = domain;
        emit CommanderAppointed(commander, domain);
    }

    function removeCommander(address commander) external onlyCommand {
        if (commanderDomain[commander] == 0) revert NotAppointed();
        delete commanderDomain[commander];
        emit CommanderRemoved(commander);
    }

    /// @param uxvL2Address the UxV's Starknet (L2) account address, as a felt.
    /// Deliberately NOT an `address` type -- see contract-level note.
    /// @param role small integer role code, meaningful only to the L2 side.
    /// @dev payable: sendMessageToL2 requires an L1 fee; forward msg.value.
    function authorise(uint256 uxvL2Address, uint256 role) external payable {
        uint256 domain = commanderDomain[msg.sender];
        if (domain == 0) revert NotCommander();

        uint256[] memory payload = new uint256[](4);
        payload[0] = uxvL2Address;
        payload[1] = domain;
        payload[2] = role;
        payload[3] = uint256(uint160(msg.sender)); // commander, kept for the L2 audit trail

        starknetCore.sendMessageToL2{value: msg.value}(l2Registry, AUTHORISE_SELECTOR, payload);
        emit UxvAuthorised(uxvL2Address, domain, msg.sender, role);
    }
}
