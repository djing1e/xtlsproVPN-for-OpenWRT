include $(TOPDIR)/rules.mk
PKG_NAME:=xtlsprovpn
PKG_VERSION:=1.4.2
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-or-later MPL-2.0
PKG_MAINTAINER:=xtlsproVPN
include $(INCLUDE_DIR)/package.mk

define Package/xtlsprovpn
  SECTION:=net
  CATEGORY:=Network
  TITLE:=xtlsproVPN router administration
  PKGARCH:=all
  DEPENDS:=@aarch64 +luci-base +rpcd +rpcd-mod-ucode +curl +ca-bundle +ucode +ucode-mod-fs +ucode-mod-uci +ucode-mod-socket +ucode-mod-ubus +flock +coreutils-base64 +coreutils-sha256sum +coreutils-timeout +unzip +firewall4 +kmod-nft-tproxy +ip-full
endef

define Package/xtlsprovpn/description
  Subscription import, native Xray routing, DNS, monitoring and core updates.
  The Xray executable is installed separately from official upstream assets.
endef

define Build/Compile
endef

define Package/xtlsprovpn/conffiles
/etc/config/forkop_xray
/etc/config/xray_core
/etc/config/xray_lab_dns
/etc/config/xray_lab_core
/etc/config/xray_lab_schedule
/etc/config/xray_lab_netbird
/etc/config/xray_lab_rescue
endef

define Package/xtlsprovpn/install
	$(INSTALL_DIR) $(1)
	$(CP) ./files/. $(1)/
	$(INSTALL_DIR) $(1)/etc/xtlspro-rescue
	chmod 700 $(1)/etc/xtlspro-rescue
	# Install executable entry points explicitly; never inherit a lost Git mode.
	$(INSTALL_BIN) ./files/etc/init.d/* $(1)/etc/init.d/
	$(INSTALL_BIN) ./files/etc/uci-defaults/* $(1)/etc/uci-defaults/
	$(INSTALL_BIN) ./files/usr/bin/* $(1)/usr/bin/
	$(INSTALL_BIN) ./files/usr/libexec/rpcd/* $(1)/usr/libexec/rpcd/
endef

# OpenWrt default_postinst runs and removes /etc/uci-defaults entries.
# Do not invoke the one-shot initializer a second time.


$(eval $(call BuildPackage,xtlsprovpn))
