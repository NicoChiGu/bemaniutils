import copy
from typing import List, Tuple, Optional, Dict, Any

from bemani.common import APIConstants, GameConstants, ValidatedDict, Parallel
from bemani.data.interfaces import APIProviderInterface
from bemani.data.api.base import BaseGlobalData
from bemani.data.mysql.user import UserData
from bemani.data.remoteuser import RemoteUser
from bemani.data.types import UserID


class GlobalUserData(BaseGlobalData):

    def __init__(self, api: APIProviderInterface, user: UserData) -> None:
        super().__init__(api)
        self.user = user

    def __format_ddr_profile(self, profile: ValidatedDict) -> Dict[str, Any]:
        updates = {}

        area = profile.get_int('area', -1)
        if area != -1:
            updates['area'] = area

        return updates

    def __format_iidx_profile(self, profile: ValidatedDict) -> Dict[str, Any]:
        updates: Dict[str, Any] = {
            'qpro': {},
        }

        area = profile.get_int('area', -1)
        if area != -1:
            updates['pid'] = area

        qpro = profile.get_dict('qpro')
        head = qpro.get_int('head', -1)
        if head != -1:
            updates['qpro']['head'] = head
        hair = qpro.get_int('hair', -1)
        if hair != -1:
            updates['qpro']['hair'] = hair
        face = qpro.get_int('face', -1)
        if face != -1:
            updates['qpro']['face'] = face
        body = qpro.get_int('body', -1)
        if body != -1:
            updates['qpro']['body'] = body
        hand = qpro.get_int('hand', -1)
        if hand != -1:
            updates['qpro']['hand'] = hand

        return updates

    def __format_jubeat_profile(self, profile: ValidatedDict) -> Dict[str, Any]:
        return {}

    def __format_museca_profile(self, profile: ValidatedDict) -> Dict[str, Any]:
        return {}

    def __format_popn_profile(self, profile: ValidatedDict) -> Dict[str, Any]:
        updates = {}

        chara = profile.get_int('character', -1)
        if chara != -1:
            updates['chara'] = chara

        return updates

    def __format_reflec_profile(self, profile: ValidatedDict) -> Dict[str, Any]:
        updates = {}

        icon = profile.get_int('icon', -1)
        if icon != -1:
            updates['config'] = {'icon_id': icon}

        return updates

    def __format_sdvx_profile(self, profile: ValidatedDict) -> Dict[str, Any]:
        return {}

    def __format_profile(self, profile: ValidatedDict) -> ValidatedDict:
        base = {
            'name': profile.get('name', ''),
            'game': profile['game'],
            'version': profile['version'],
            'refid': profile['refid'],
            'extid': profile['extid'],
        }

        profilegame = GameConstants(profile['game'])
        if profilegame == GameConstants.DDR:
            base.update(self.__format_ddr_profile(profile))
        if profilegame == GameConstants.IIDX:
            base.update(self.__format_iidx_profile(profile))
        if profilegame == GameConstants.JUBEAT:
            base.update(self.__format_jubeat_profile(profile))
        if profilegame == GameConstants.MUSECA:
            base.update(self.__format_museca_profile(profile))
        if profilegame == GameConstants.POPN_MUSIC:
            base.update(self.__format_popn_profile(profile))
        if profilegame == GameConstants.REFLEC_BEAT:
            base.update(self.__format_reflec_profile(profile))
        if profilegame == GameConstants.SDVX:
            base.update(self.__format_sdvx_profile(profile))

        return ValidatedDict(base)

    def __profile_request(self, game: GameConstants, version: int, userid: UserID, exact: bool) -> Optional[ValidatedDict]:
        # First, get or create the extid/refid for this virtual user
        cardid = RemoteUser.userid_to_card(userid)
        refid = self.user.get_refid(game, version, userid)
        extid = self.user.get_extid(game, version, userid)

        profiles = Parallel.flatten(Parallel.call(
            [client.get_profiles for client in self.clients],
            game,
            version,
            APIConstants.ID_TYPE_CARD,
            [cardid],
        ))
        for profile in profiles:
            cards = [card.upper() for card in profile.get('cards', [])]
            if cardid in cards:
                # Sanitize the returned data
                profile = copy.deepcopy(profile)
                del profile['cards']

                exact_match = profile.get('match', 'partial') == 'exact'
                if exact and (not exact_match):
                    # This is a partial match, not for this game/version
                    continue

                if 'match' in profile:
                    del profile['match']

                # Add in our defaults we always provide
                profile['game'] = game.value
                profile['version'] = version if exact_match else 0
                profile['refid'] = refid
                profile['extid'] = extid

                return self.__format_profile(ValidatedDict(profile))

        return None

    def from_cardid(self, cardid: str) -> Optional[UserID]:
        userid = self.user.from_cardid(cardid)
        if userid is None:
            userid = RemoteUser.card_to_userid(cardid)
        return userid

    def from_refid(self, game: GameConstants, version: int, refid: str) -> Optional[UserID]:
        return self.user.from_refid(game, version, refid)

    def from_extid(self, game: GameConstants, version: int, extid: int) -> Optional[UserID]:
        return self.user.from_extid(game, version, extid)

    def get_profile(self, game: GameConstants, version: int, userid: UserID) -> Optional[ValidatedDict]:
        if RemoteUser.is_remote(userid):
            return self.__profile_request(game, version, userid, exact=True)
        else:
            return self.user.get_profile(game, version, userid)

    def get_any_profile(self, game: GameConstants, version: int, userid: UserID) -> Optional[ValidatedDict]:
        if RemoteUser.is_remote(userid):
            return self.__profile_request(game, version, userid, exact=False)
        else:
            return self.user.get_any_profile(game, version, userid)

    def get_any_profiles(self, game: GameConstants, version: int, userids: List[UserID]) -> List[Tuple[UserID, Optional[ValidatedDict]]]:
        if len(userids) == 0:
            return []

        remote_ids = [
            userid for userid in userids
            if RemoteUser.is_remote(userid)
        ]
        local_ids = [
            userid for userid in userids
            if not RemoteUser.is_remote(userid)
        ]

        if len(remote_ids) == 0:
            # We only have local profiles here, just pass on to the underlying layer
            return self.user.get_any_profiles(game, version, local_ids)
        else:
            # We have to fetch some local profiles and some remote profiles, and then
            # merge them together
            card_to_userid = {
                RemoteUser.userid_to_card(userid): userid
                for userid in remote_ids
            }

            local_profiles, remote_profiles = Parallel.execute([
                lambda: self.user.get_any_profiles(game, version, local_ids),
                lambda: Parallel.flatten(Parallel.call(
                    [client.get_profiles for client in self.clients],
                    game,
                    version,
                    APIConstants.ID_TYPE_CARD,
                    [RemoteUser.userid_to_card(userid) for userid in remote_ids],
                ))
            ])

            for profile in remote_profiles:
                cards = [card.upper() for card in profile.get('cards', [])]
                for card in cards:
                    # Map it back to the requested user
                    userid = card_to_userid.get(card)
                    if userid is None:
                        continue

                    # Sanitize the returned data
                    profile = copy.deepcopy(profile)
                    del profile['cards']

                    exact_match = profile.get('match', 'partial') == 'exact'

                    if 'match' in profile:
                        del profile['match']

                    refid = self.user.get_refid(game, version, userid)
                    extid = self.user.get_extid(game, version, userid)

                    # Add in our defaults we always provide
                    profile['game'] = game.value
                    profile['version'] = version if exact_match else 0
                    profile['refid'] = refid
                    profile['extid'] = extid

                    local_profiles.append(
                        (userid, self.__format_profile(ValidatedDict(profile))),
                    )

                    # Mark that we saw this card/user
                    del card_to_userid[card]

            # Finally, mark all missing remote profiles as None
            for card in card_to_userid:
                local_profiles.append((card_to_userid[card], None))

            return local_profiles

    def get_all_profiles(self, game: GameConstants, version: int) -> List[Tuple[UserID, ValidatedDict]]:
        # Fetch local and remote profiles, and then merge by adding remote profiles to local
        # profiles when we don't have a profile for that user ID yet.
        local_cards, local_profiles, remote_profiles = Parallel.execute([
            self.user.get_all_cards,
            lambda: self.user.get_all_profiles(game, version),
            lambda: Parallel.flatten(Parallel.call(
                [client.get_profiles for client in self.clients],
                game,
                version,
                APIConstants.ID_TYPE_SERVER,
                [],
            )),
        ])

        card_to_id = {cardid: userid for (cardid, userid) in local_cards}
        id_to_profile = {userid: profile for (userid, profile) in local_profiles}

        for profile in remote_profiles:
            cardids = sorted([card.upper() for card in profile.get('cards', [])])
            if len(cardids) == 0:
                # We don't care about anonymous profiles
                continue

            local_cards = [cardid for cardid in cardids if cardid in card_to_id]
            if len(local_cards) > 0:
                # We have a local version of this profile!
                continue

            # Create a fake user with this profile
            del profile['cards']

            exact_match = profile.get('match', 'partial') == 'exact'
            if not exact_match:
                continue

            userid = RemoteUser.card_to_userid(cardids[0])
            refid = self.user.get_refid(game, version, userid)
            extid = self.user.get_extid(game, version, userid)

            # Add in our defaults we always provide
            profile['game'] = game.value
            profile['version'] = version
            profile['refid'] = refid
            profile['extid'] = extid

            id_to_profile[userid] = self.__format_profile(ValidatedDict(profile))

        return [(userid, id_to_profile[userid]) for userid in id_to_profile]
